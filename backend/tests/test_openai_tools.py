import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app.ai.llm import LLMError
from app.ai.openai import OpenAILLMProvider
from app.ai.tools import TOOL_NAMES, ToolArguments, ToolCall
from app.core.config import Settings


def function_response(name="retrieve_documentation", arguments='{"document_id":null}'):
    return {
        "status": "completed",
        "output": [
            {
                "type": "function_call",
                "status": "completed",
                "name": name,
                "arguments": arguments,
                "call_id": "call-fixture",
            }
        ],
    }


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_tool_selection_request_and_typed_arguments(name) -> None:
    document_id = uuid4()

    def handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-5.4-mini"
        assert payload["store"] is False
        assert payload["tool_choice"] == "required"
        assert payload["parallel_tool_calls"] is False
        assert [t["name"] for t in payload["tools"]] == list(TOOL_NAMES)
        for tool in payload["tools"]:
            assert tool["strict"] is True
            assert tool["parameters"]["additionalProperties"] is False
            assert tool["parameters"]["required"] == ["document_id"]
        assert json.loads(payload["input"][1]["content"]) == {
            "question": "Question",
            "selected_document_id": str(document_id),
        }
        return httpx.Response(
            200,
            json=function_response(name, json.dumps({"document_id": str(document_id)})),
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            call = await OpenAILLMProvider(
                Settings(openai_api_key="fixture"), client
            ).choose_tool("Question", document_id)
            assert call.name == name
            assert call.arguments.document_id == document_id
            assert call.call_id == "call-fixture"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "bad_json",
        "extra_arguments",
        "missing_arguments",
        "invalid_uuid",
        "multiple",
        "empty",
        "prose",
        "incomplete",
        "null_output",
        "bad_item",
        "missing_id",
    ],
)
def test_invalid_tool_choices_fail_closed(case) -> None:
    payload = function_response()
    call = payload["output"][0]
    if case == "unknown":
        call["name"] = "run_shell"
    elif case == "bad_json":
        call["arguments"] = "private-invalid-json"
    elif case == "extra_arguments":
        call["arguments"] = '{"document_id":null,"command":"private"}'
    elif case == "missing_arguments":
        call["arguments"] = "{}"
    elif case == "invalid_uuid":
        call["arguments"] = '{"document_id":"private"}'
    elif case == "multiple":
        payload["output"].append(call.copy())
    elif case == "empty":
        payload["output"] = []
    elif case == "prose":
        call["type"] = "message"
    elif case == "incomplete":
        call["status"] = "in_progress"
    elif case == "null_output":
        payload["output"] = None
    elif case == "bad_item":
        payload["output"] = [None]
    elif case == "missing_id":
        del call["call_id"]

    async def scenario():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(LLMError, match="invalid tool choice") as error:
                await OpenAILLMProvider(
                    Settings(openai_api_key="fixture"), client
                ).choose_tool("Question", None)
            assert "private" not in str(error.value)

    asyncio.run(scenario())


def test_tool_output_is_matched_to_call_and_final_answer_is_structured() -> None:
    def handler(request):
        body = json.loads(request.content)
        assert "tools" not in body
        assert body["text"]["format"]["strict"] is True
        call, result = body["input"][-2:]
        assert call["type"] == "function_call"
        assert result["type"] == "function_call_output"
        assert call["call_id"] == result["call_id"] == "call-fixture"
        assert json.loads(result["output"]) == {"sources": [{"text": "untrusted"}]}
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {"answer": "Fact [S1].", "citation_labels": ["S1"]}
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAILLMProvider(Settings(openai_api_key="fixture"), client)
            call = ToolCall(
                "summarize_document", ToolArguments(document_id=None), "call-fixture"
            )
            answer = await provider.complete_tool(
                "Question", call, {"sources": [{"text": "untrusted"}]}, "system"
            )
            assert answer.citation_labels == ["S1"]

    asyncio.run(scenario())
