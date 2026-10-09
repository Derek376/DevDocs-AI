from unittest.mock import AsyncMock

import pytest

from app.ai.llm import LLMError
from app.persistence.database import get_session
from app.services.search import DocumentNotFoundError


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 2001},
        {"question": "Question", "selected_document_id": "invalid"},
        {"question": "Question", "tool": "run_shell"},
    ],
)
def test_agent_request_validation(client, payload):
    async def session():
        yield AsyncMock()

    client.app.dependency_overrides[get_session] = session
    assert client.post("/agent/questions", json=payload).status_code == 422


@pytest.mark.parametrize(
    "error,status",
    [
        (LLMError("Safe tool failure"), 502),
        (DocumentNotFoundError("Document not found."), 404),
    ],
)
def test_agent_errors_use_safe_api_contract(client, monkeypatch, error, status):
    async def session():
        yield AsyncMock()

    client.app.dependency_overrides[get_session] = session
    monkeypatch.setattr("app.api.agent.run_agent", AsyncMock(side_effect=error))
    response = client.post("/agent/questions", json={"question": "Question"})
    assert response.status_code == status
    assert response.json()["detail"] == str(error)
    assert response.headers["X-Request-ID"]
