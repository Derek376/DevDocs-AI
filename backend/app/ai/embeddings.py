"""Minimal embedding contract and validation shared by indexing and search."""

import math
from typing import Protocol


class EmbeddingError(RuntimeError):
    """Safe provider failure; internal responses must not be returned to users."""


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def validate_vectors(vectors: object, count: int, dimensions: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != count:
        raise EmbeddingError("Embedding provider returned an unexpected vector count.")
    result: list[list[float]] = []
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise EmbeddingError(
                "Embedding dimension differs from EMBEDDING_DIMENSIONS."
            )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or abs(value) > 3.4e38
            or not math.isfinite(value)
            for value in vector
        ):
            raise EmbeddingError("Embedding provider returned invalid vector values.")
        values = [float(value) for value in vector]
        if not any(values):
            raise EmbeddingError("Embedding provider returned a zero vector.")
        norm = math.hypot(*values)
        result.append([value / norm for value in values])
    return result
