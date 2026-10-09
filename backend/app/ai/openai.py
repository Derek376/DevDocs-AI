"""OpenAI HTTP adapters; retrieval and citation validation stay in the service."""

import json
from uuid import UUID

import httpx

from app.ai.embeddings import EmbeddingError, validate_vectors
from app.ai.llm import GeneratedAnswer, LLMError
from app.ai.tools import (
    ROUTER_PROMPT,
    TOOL_NAMES,
    ToolArguments,
    ToolCall,
    tool_definitions,
)
from app.core.config import Settings


class OpenAIEmbeddingProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.model = settings.embedding_model
        self.model_id = f"openai:{self.model}"
        self.dimensions = settings.embedding_dimensions
        self.api_key = settings.openai_api_key
        self.client = client
        self.timeout = settings.embedding_timeout_seconds

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.api_key is None:
            raise EmbeddingError(
                "OpenAI is not configured. Set OPENAI_API_KEY in the root .env "
                "and restart the backend."
            )
        try:
            response = await self.client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key.get_secret_value()}"},
                json={
                    "model": self.model,
                    "input": texts,
                    "dimensions": self.dimensions,
                    "encoding_format": "float",
                },
                timeout=self.timeout,
            )
            if response.status_code in (401, 403):
                raise EmbeddingError(
                    "OpenAI authentication or permission failed. Check the backend "
                    "API key and project model access."
                )
            if response.status_code == 429:
                raise EmbeddingError(
                    "OpenAI rate or quota limit reached. Check API billing and limits, "
                    "then retry later."
                )
            if response.status_code == 404:
                raise EmbeddingError(
                    "OpenAI embedding model is unavailable. Check EMBEDDING_MODEL "
                    "and project access."
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingError(
                "OpenAI embedding request failed. Check network access, input length "
                "and embedding settings, then retry."
            ) from exc
        try:
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, list) or len(data) != len(texts):
                raise ValueError("Unexpected embedding count")
            # Match by input index, never assume the response array is ordered.
            vectors: list[object] = [None] * len(texts)
            seen: set[int] = set()
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError("Invalid embedding item")
                index = item.get("index")
                if (
                    type(index) is not int
                    or not 0 <= index < len(texts)
                    or index in seen
                ):
                    raise ValueError("Invalid embedding index")
                seen.add(index)
                vectors[index] = item.get("embedding")
            return validate_vectors(vectors, len(texts), self.dimensions)
        except (ValueError, TypeError) as exc:
            raise EmbeddingError(
                "OpenAI returned an invalid embedding response. Please retry."
            ) from exc


class OpenAILLMProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.model = settings.llm_model
        self.model_id = f"openai:{self.model}"
        self.api_key = settings.openai_api_key
        self.client = client
        self.timeout = settings.llm_timeout_seconds

    async def choose_tool(self, question: str, document_id: UUID | None) -> ToolCall:
        data = await self._request(
            {
                "input": [
                    {"role": "system", "content": ROUTER_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "question": question,
                                "selected_document_id": str(document_id)
                                if document_id
                                else None,
                            }
                        ),
                    },
                ],
                "tools": tool_definitions(),
                "tool_choice": "required",
                "parallel_tool_calls": False,
            }
        )
        try:
            output = data["output"]
            if not isinstance(output, list):
                raise ValueError("Invalid output")
            # No prose or extra tool may bypass the bounded decision contract.
            calls = [item for item in output if item.get("type") != "reasoning"]
            if len(calls) != 1:
                raise ValueError("Expected exactly one tool")
            call = calls[0]
            if (
                call.get("type") != "function_call"
                or call.get("status") != "completed"
                or call.get("name") not in TOOL_NAMES
            ):
                raise ValueError("Invalid tool")
            call_id = call.get("call_id")
            if not isinstance(call_id, str) or not call_id or len(call_id) > 256:
                raise ValueError("Invalid call ID")
            arguments = ToolArguments.model_validate_json(call["arguments"])
            return ToolCall(call["name"], arguments, call_id)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise LLMError(
                "OpenAI returned an invalid tool choice. Please retry."
            ) from exc

    async def complete_tool(
        self, question: str, call: ToolCall, output: dict, system_prompt: str
    ) -> GeneratedAnswer:
        return await self._generate(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
                {
                    "type": "function_call",
                    "name": call.name,
                    "call_id": call.call_id,
                    "arguments": call.arguments.model_dump_json(),
                    "status": "completed",
                },
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(output, ensure_ascii=False, default=str),
                },
            ]
        )

    async def generate(self, system_prompt: str, user_prompt: str) -> GeneratedAnswer:
        return await self._generate(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    async def _request(self, payload: dict) -> dict:
        if self.api_key is None:
            raise LLMError(
                "OpenAI is not configured. Set OPENAI_API_KEY in the root .env "
                "and restart the backend."
            )
        try:
            response = await self.client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self.api_key.get_secret_value()}"},
                json={
                    "model": self.model,
                    "reasoning": {"effort": "none"},
                    "max_output_tokens": 1024,
                    "store": False,
                    **payload,
                },
                timeout=self.timeout,
            )
            if response.status_code in (401, 403):
                raise LLMError(
                    "OpenAI authentication or permission failed. Check the backend "
                    "API key and project model access."
                )
            if response.status_code == 429:
                raise LLMError(
                    "OpenAI rate or quota limit reached. Check API billing and limits, "
                    "then retry later."
                )
            if response.status_code == 404:
                raise LLMError(
                    "OpenAI model is unavailable. Check LLM_MODEL and project access."
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(
                "OpenAI generation failed. Check network access and model "
                "configuration, then retry."
            ) from exc

        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected response object")
            if data.get("status") != "completed":
                raise LLMError(
                    "OpenAI returned an incomplete or failed answer. "
                    "Try a more focused question or retry."
                )
            return data
        except (ValueError, TypeError) as exc:
            raise LLMError(
                "OpenAI returned an invalid answer format. Please retry."
            ) from exc

    async def _generate(self, input_items: list[dict]) -> GeneratedAnswer:
        data = await self._request(
            {
                "input": input_items,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "grounded_answer",
                        "strict": True,
                        "schema": GeneratedAnswer.model_json_schema(),
                    }
                },
            }
        )
        try:
            output = data.get("output")
            if not isinstance(output, list):
                raise ValueError("Expected output items")
            texts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    raise ValueError("Expected output object")
                # The output may include reasoning items before the answer message.
                if item.get("type") != "message":
                    continue
                if item.get("status") != "completed":
                    raise ValueError("Incomplete message")
                content = item.get("content")
                if not isinstance(content, list):
                    raise ValueError("Expected message content")
                for part in content:
                    if not isinstance(part, dict):
                        raise ValueError("Expected content object")
                    if part.get("type") == "refusal":
                        raise LLMError(
                            "OpenAI declined to answer this question. "
                            "Try rephrasing it."
                        )
                    if part.get("type") == "output_text":
                        text = part.get("text")
                        if not isinstance(text, str):
                            raise ValueError("Expected text")
                        texts.append(text)
            if len(texts) != 1:
                raise ValueError("Expected one structured answer")
            return GeneratedAnswer.model_validate_json(texts[0])
        except (ValueError, TypeError) as exc:
            raise LLMError(
                "OpenAI returned an invalid answer format. Please retry."
            ) from exc
