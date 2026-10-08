"""OpenAI Responses adapter; retrieval and citation validation stay in the service."""

import httpx

from app.ai.llm import GeneratedAnswer, LLMError
from app.core.config import Settings


class OpenAILLMProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.model = settings.llm_model
        self.model_id = f"openai:{self.model}"
        self.api_key = settings.openai_api_key
        self.client = client
        self.timeout = settings.llm_timeout_seconds

    async def generate(self, system_prompt: str, user_prompt: str) -> GeneratedAnswer:
        if self.api_key is None:
            raise LLMError(
                "OpenAI is not configured. Set OPENAI_API_KEY in the backend .env "
                "and restart the backend."
            )
        try:
            response = await self.client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self.api_key.get_secret_value()}"},
                json={
                    "model": self.model,
                    "input": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "grounded_answer",
                            "strict": True,
                            "schema": GeneratedAnswer.model_json_schema(),
                        }
                    },
                    "reasoning": {"effort": "none"},
                    "max_output_tokens": 1024,
                    "store": False,
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
