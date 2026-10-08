import asyncio
import json

import httpx
import pytest

from app.ai.llm import GeneratedAnswer, LLMError
from app.ai.ollama import OllamaLLMProvider
from app.core.config import Settings


def test_chat_adapter_sends_roles_schema_and_generation_limits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert body["model"] == "llama3.2:1b"
        assert body["stream"] is False
        assert body["messages"] == [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "evidence"},
        ]
        assert body["format"] == GeneratedAnswer.model_json_schema()
        assert body["options"]["temperature"] == 0
        assert body["options"]["num_predict"] == 512
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": json.dumps(
                        {"answer": "Use rollback [S1].", "citation_labels": ["S1"]}
                    )
                },
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaLLMProvider(Settings(), client)
            reply = await provider.generate("instructions", "evidence")
            assert reply.answer == "Use rollback [S1]."
            assert reply.citation_labels == ["S1"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case",
    [
        "timeout",
        "http",
        "bad_json",
        "incomplete",
        "length",
        "bad_message",
        "bad_content",
        "bad_schema",
    ],
)
def test_generation_failures_have_safe_errors(case: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if case == "timeout":
            raise httpx.ReadTimeout("private-host", request=request)
        if case == "http":
            return httpx.Response(500, text="private-provider-error")
        if case == "bad_json":
            return httpx.Response(200, text="private-invalid-json")
        payload = {
            "done": True,
            "message": {"content": '{"answer":"text","citation_labels":[]}'},
        }
        if case == "incomplete":
            payload["done"] = False
        elif case == "length":
            payload["done_reason"] = "length"
        elif case == "bad_message":
            payload["message"] = None
        elif case == "bad_content":
            payload["message"]["content"] = "private-unstructured-text"
        elif case == "bad_schema":
            payload["message"]["content"] = '{"answer":42,"citation_labels":[]}'
        return httpx.Response(200, json=payload)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(LLMError) as error:
                await OllamaLLMProvider(Settings(), client).generate(
                    "system", "question"
                )
            assert "private" not in str(error.value)

    asyncio.run(scenario())
