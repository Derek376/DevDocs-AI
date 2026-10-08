"""Local Ollama embedding adapter; owns no database or HTTP route logic."""

import httpx

from app.ai.embeddings import EmbeddingError, validate_vectors
from app.ai.llm import GeneratedAnswer, LLMError
from app.core.config import Settings


class OllamaEmbeddingProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.model = settings.embedding_model
        self.model_id = f"ollama:{self.model}"
        self.dimensions = settings.embedding_dimensions
        self.client = client
        self.url = settings.ollama_base_url.rstrip("/") + "/api/embed"
        self.timeout = settings.embedding_timeout_seconds

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self.client.post(
                self.url,
                json={"model": self.model, "input": texts, "truncate": False},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            vectors = data.get("embeddings") if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingError(
                "Embedding provider is unavailable or rejected the input. "
                "Check Ollama, the model download, and its input length limit."
            ) from exc
        return validate_vectors(vectors, len(texts), self.dimensions)


class OllamaLLMProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.model = settings.llm_model
        self.model_id = f"ollama:{self.model}"
        self.client = client
        self.url = settings.ollama_base_url.rstrip("/") + "/api/chat"
        self.timeout = settings.llm_timeout_seconds

    async def generate(self, system_prompt: str, user_prompt: str) -> GeneratedAnswer:
        try:
            response = await self.client.post(
                self.url,
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "format": GeneratedAnswer.model_json_schema(),
                    "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 512},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get("done") is not True:
                raise LLMError("LLM returned an incomplete response. Please retry.")
            if data.get("done_reason") == "length":
                raise LLMError(
                    "LLM reached its output limit. Try a more focused question."
                )
            content = data.get("message", {}).get("content")
            if not isinstance(content, str):
                raise LLMError("LLM returned an invalid response. Please retry.")
            return GeneratedAnswer.model_validate_json(content)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            raise LLMError(
                "LLM generation failed. Check Ollama and the configured chat model, "
                "then retry."
            ) from exc
