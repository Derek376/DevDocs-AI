import asyncio
import json

import httpx
import pytest

from app.ai.embeddings import EmbeddingError
from app.ai.openai import OpenAIEmbeddingProvider
from app.core.config import Settings


def settings() -> Settings:
    return Settings(openai_api_key="fixture-secret", embedding_dimensions=2)


def test_embeddings_request_and_reordered_batch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.openai.com/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer fixture-secret"
        assert json.loads(request.content) == {
            "model": "text-embedding-3-small",
            "input": ["first", "second"],
            "dimensions": 2,
            "encoding_format": "float",
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0, 2]},
                    {"index": 0, "embedding": [3, 4]},
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIEmbeddingProvider(settings(), client)
            assert provider.model_id == "openai:text-embedding-3-small"
            assert await provider.embed(["first", "second"]) == [[0.6, 0.8], [0, 1]]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "code,expected",
    [
        (401, "authentication"),
        (403, "permission"),
        (404, "model is unavailable"),
        (429, "rate or quota"),
        (400, "input length"),
        (500, "request failed"),
    ],
)
def test_embedding_http_errors_are_safe_and_actionable(code, expected) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, text="private-provider-details fixture-secret")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(EmbeddingError, match=expected) as error:
                await OpenAIEmbeddingProvider(settings(), client).embed(["text"])
            assert "private" not in str(error.value)
            assert "fixture-secret" not in str(error.value)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"data": []},
        {"data": [None]},
        {"data": [{"index": True, "embedding": [1, 0]}]},
        {"data": [{"index": -1, "embedding": [1, 0]}]},
        {"data": [{"index": 1, "embedding": [1, 0]}]},
        {"data": [{"index": 0}]},
        {"data": [{"index": 0, "embedding": [1]}]},
        {"data": [{"index": 0, "embedding": [0, 0]}]},
        {"data": [{"index": 0, "embedding": ["private", 0]}]},
    ],
)
def test_invalid_embedding_response_is_rejected(payload) -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(EmbeddingError) as error:
                await OpenAIEmbeddingProvider(settings(), client).embed(["text"])
            assert "private" not in str(error.value)

    asyncio.run(scenario())


def test_duplicate_response_indices_are_rejected() -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [{"index": 0, "embedding": [1, 0]}] * 2,
                },
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(EmbeddingError, match="invalid embedding response"):
                await OpenAIEmbeddingProvider(settings(), client).embed(["one", "two"])

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["timeout", "bad_json"])
def test_embedding_transport_and_json_errors_are_safe(case) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if case == "timeout":
            raise httpx.ReadTimeout("private-network-details", request=request)
        return httpx.Response(200, text="private-invalid-json")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(EmbeddingError) as error:
                await OpenAIEmbeddingProvider(settings(), client).embed(["text"])
            assert "private" not in str(error.value)

    asyncio.run(scenario())


def test_missing_key_and_empty_batch_make_no_http_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No HTTP request is expected")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIEmbeddingProvider(Settings(), client)
            assert await provider.embed([]) == []
            with pytest.raises(EmbeddingError, match="Set OPENAI_API_KEY"):
                await provider.embed(["text"])

    asyncio.run(scenario())
