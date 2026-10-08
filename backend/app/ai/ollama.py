"""Local Ollama embedding adapter; owns no database or HTTP route logic."""

import httpx

from app.ai.embeddings import EmbeddingError, validate_vectors
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
