import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai.llm import GeneratedAnswer, LLMError
from app.ai.ollama import OllamaEmbeddingProvider, OllamaLLMProvider
from app.ai.openai import OpenAILLMProvider
from app.core.config import Settings
from app.main import create_app


def settings() -> Settings:
    return Settings(
        llm_provider="openai", llm_model="gpt-5.4-mini", openai_api_key="fixture-secret"
    )


def completed_response() -> dict:
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {"answer": "Use ROLLBACK [S1].", "citation_labels": ["S1"]}
                        ),
                    }
                ],
            },
        ],
    }


def test_openai_request_uses_auth_schema_and_no_response_storage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == "Bearer fixture-secret"
        body = json.loads(request.content)
        assert body["model"] == "gpt-5.4-mini"
        assert body["input"] == [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "evidence"},
        ]
        assert body["text"]["format"] == {
            "type": "json_schema",
            "name": "grounded_answer",
            "strict": True,
            "schema": GeneratedAnswer.model_json_schema(),
        }
        assert body["store"] is False
        assert body["reasoning"] == {"effort": "none"}
        assert body["max_output_tokens"] == 1024
        assert "temperature" not in body
        return httpx.Response(200, json=completed_response())

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAILLMProvider(settings(), client)
            assert provider.model_id == "openai:gpt-5.4-mini"
            reply = await provider.generate("instructions", "evidence")
            assert reply.answer == "Use ROLLBACK [S1]."
            assert reply.citation_labels == ["S1"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (401, "authentication"),
        (403, "permission"),
        (404, "model is unavailable"),
        (429, "rate or quota"),
        (400, "generation failed"),
        (500, "generation failed"),
    ],
)
def test_openai_http_failures_have_safe_actionable_errors(code, expected) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, text="private-provider-details fixture-secret")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(LLMError, match=expected) as error:
                await OpenAILLMProvider(settings(), client).generate("system", "input")
            assert "private" not in str(error.value)
            assert "fixture-secret" not in str(error.value)

    asyncio.run(scenario())


def test_openai_timeout_does_not_expose_transport_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private-network-details", request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(LLMError, match="generation failed") as error:
                await OpenAILLMProvider(settings(), client).generate("system", "input")
            assert "private" not in str(error.value)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case",
    [
        "bad_json",
        "non_object",
        "incomplete",
        "failed",
        "missing_status",
        "missing_output",
        "bad_item",
        "incomplete_message",
        "bad_content",
        "bad_part",
        "bad_text",
        "bad_answer_json",
        "bad_schema",
        "empty_output",
        "duplicate_text",
        "refusal",
    ],
)
def test_openai_rejects_incomplete_refused_or_invalid_answers(case: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if case == "bad_json":
            return httpx.Response(200, text="private-provider-details")
        if case == "non_object":
            return httpx.Response(200, json=[])
        payload = completed_response()
        message = payload["output"][1]
        part = message["content"][0]
        if case in ("incomplete", "failed"):
            payload["status"] = case
        elif case == "missing_status":
            del payload["status"]
        elif case == "missing_output":
            del payload["output"]
        elif case == "bad_item":
            payload["output"] = [None]
        elif case == "incomplete_message":
            message["status"] = "incomplete"
        elif case == "bad_content":
            message["content"] = None
        elif case == "bad_part":
            message["content"] = [None]
        elif case == "bad_text":
            part["text"] = 42
        elif case == "bad_answer_json":
            part["text"] = "private-invalid-json"
        elif case == "bad_schema":
            part["text"] = '{"answer":42,"citation_labels":[]}'
        elif case == "empty_output":
            payload["output"] = []
        elif case == "duplicate_text":
            message["content"].append(part.copy())
        elif case == "refusal":
            message["content"] = [{"type": "refusal", "refusal": "private-details"}]
        return httpx.Response(200, json=payload)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(LLMError) as error:
                await OpenAILLMProvider(settings(), client).generate("system", "input")
            assert "private" not in str(error.value)
            assert "fixture-secret" not in str(error.value)

    asyncio.run(scenario())


def test_missing_api_key_is_useful_and_does_not_send_a_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Missing credentials must not result in an HTTP request")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAILLMProvider(
                Settings(llm_provider="openai", llm_model="gpt-5.4-mini"), client
            )
            with pytest.raises(LLMError, match="Set OPENAI_API_KEY"):
                await provider.generate("system", "input")

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_app_selects_generation_provider_without_changing_embeddings(provider) -> None:
    config = Settings(
        llm_provider=provider,
        llm_model="gpt-5.4-mini" if provider == "openai" else "llama3.2:1b",
    )
    with TestClient(create_app(config)) as client:
        expected = OpenAILLMProvider if provider == "openai" else OllamaLLMProvider
        assert isinstance(client.app.state.llm_provider, expected)
        assert isinstance(client.app.state.embedding_provider, OllamaEmbeddingProvider)
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize("value", ["", "  ", None])
def test_blank_openai_key_is_treated_as_missing(value) -> None:
    assert Settings(openai_api_key=value).openai_api_key is None


def test_openai_key_is_masked_in_settings_and_invalid_provider_is_rejected() -> None:
    assert "fixture-secret" not in repr(settings())
    with pytest.raises(ValueError, match="llm_provider"):
        Settings(llm_provider="unsupported")
