import asyncio
import json

import httpx
import pytest

from app.ai.embeddings import EmbeddingError, validate_vectors
from app.ai.ollama import OllamaEmbeddingProvider
from app.core.config import Settings


@pytest.mark.parametrize(
    "vectors",
    [
        None,
        [],
        [[1]],
        [[0, 0]],
        [[True, 1]],
        [[float("nan"), 1]],
        [[float("inf"), 1]],
        [["x", 1]],
        [[10**1000, 1]],
    ],
)
def test_invalid_provider_vectors_are_rejected(vectors: object) -> None:
    with pytest.raises(EmbeddingError):
        validate_vectors(vectors, 1, 2)


def test_vectors_are_normalized_without_changing_direction() -> None:
    assert validate_vectors([[3, 4]], 1, 2) == [[0.6, 0.8]]
    assert validate_vectors([[1e-50, 0]], 1, 2) == [[1, 0]]


def test_ollama_request_and_batch_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {
            "model": "embeddinggemma",
            "input": ["first", "second"],
            "truncate": False,
        }
        assert request.url.path == "/api/embed"
        return httpx.Response(200, json={"embeddings": [[1, 0], [0, 1]]})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaEmbeddingProvider(Settings(embedding_dimensions=2), client)
            assert await provider.embed(["first", "second"]) == [[1, 0], [0, 1]]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case", ["timeout", "http_error", "bad_json", "missing_vectors"]
)
def test_provider_errors_do_not_expose_internal_responses(case: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if case == "timeout":
            raise httpx.ReadTimeout("private-host", request=request)
        if case == "http_error":
            return httpx.Response(500, text="private-provider-details")
        if case == "bad_json":
            return httpx.Response(200, text="private-invalid-json")
        return httpx.Response(200, json={"error": "private-provider-details"})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaEmbeddingProvider(Settings(embedding_dimensions=2), client)
            with pytest.raises(EmbeddingError) as error:
                await provider.embed(["text"])
            assert "private" not in str(error.value)

    asyncio.run(scenario())
