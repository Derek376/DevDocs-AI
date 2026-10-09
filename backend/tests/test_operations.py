"""Safe error boundaries, request correlation and privacy of application logs."""

import asyncio
import json
import logging
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.ai.llm import LLMError
from app.core.config import Settings
from app.core.logging import JsonFormatter, configure_logging, logger
from app.core.middleware import RequestLoggingMiddleware
from app.persistence.database import get_session


@pytest.fixture
def logs(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> Iterator[pytest.LogCaptureFixture]:
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


def completed(logs: pytest.LogCaptureFixture) -> list[dict]:
    formatter = JsonFormatter()
    return [
        json.loads(formatter.format(record))
        for record in logs.records
        if record.name == "devdocs" and record.getMessage() == "request_completed"
    ]


def test_correlation_uses_new_ids_and_never_logs_raw_urls(
    client: TestClient,
    logs: pytest.LogCaptureFixture,
) -> None:
    first = client.get(
        "/health?api_key=private-query",
        headers={
            "X-Request-ID": "untrusted-id",
            "Authorization": "Bearer private-key",
        },
    )
    second = client.get("/unknown-private-path?token=private-query")
    assert re.fullmatch(r"[a-f0-9]{32}", first.headers["X-Request-ID"])
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    rows = completed(logs)
    assert rows[0]["request_id"] == first.headers["X-Request-ID"]
    assert rows[0]["route"] == "/health"
    assert rows[1]["route"] == "unmatched"
    assert rows[1]["status"] == 404
    assert "private" not in json.dumps(rows)
    assert "untrusted-id" not in json.dumps(rows)


def test_unexpected_failure_is_safe_json_with_correlated_error_log(
    client: TestClient,
    logs: pytest.LogCaptureFixture,
) -> None:
    @client.app.get("/crash")
    async def crash():
        raise RuntimeError("private-password-and-document-text")

    response = client.get("/crash")
    assert response.status_code == 500
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "Please try again" in response.json()["detail"]
    assert "private-password" not in response.text + logs.text
    row = completed(logs)[0]
    assert row["status"] == 500
    assert row["error_type"] == "RuntimeError"
    assert row["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize("kind", ["provider", "database"])
def test_expected_failures_keep_useful_messages_without_internal_details(
    client: TestClient,
    logs: pytest.LogCaptureFixture,
    kind: str,
) -> None:
    @client.app.get("/failure")
    async def failure():
        if kind == "provider":
            raise LLMError("LLM is unavailable. Please retry.")
        raise OperationalError("SELECT private_sql", {}, Exception("private-password"))

    response = client.get("/failure")
    assert response.status_code == (502 if kind == "provider" else 503)
    assert "private" not in response.text + logs.text
    assert completed(logs)[0]["error_type"] == (
        "LLMError" if kind == "provider" else "OperationalError"
    )


def test_validation_does_not_echo_submitted_question_or_bad_values(
    client: TestClient,
    logs: pytest.LogCaptureFixture,
) -> None:
    async def unused_session():
        yield None

    client.app.dependency_overrides[get_session] = unused_session
    response = client.post(
        "/questions",
        json={
            "question": "private-document-question",
            "top_k": "private-invalid-input",
        },
    )
    assert response.status_code == 422
    assert all(
        set(error) == {"loc", "msg", "type"} for error in response.json()["detail"]
    )
    assert "private" not in response.text + logs.text
    assert completed(logs)[0]["route"] == "/questions"


def test_logs_use_route_template_instead_of_document_identifiers(
    client: TestClient,
    logs: pytest.LogCaptureFixture,
) -> None:
    client.get("/documents/private-document-id/chunks")
    row = completed(logs)[0]
    assert row["route"] == "/documents/{document_id}/chunks"
    assert "private-document-id" not in json.dumps(row)


def test_formatter_ignores_arbitrary_messages_exceptions_and_extra_data() -> None:
    record = logging.LogRecord(
        "devdocs", logging.ERROR, "", 0, "private-password", (), None
    )
    record.question = "private-question"
    record.api_key = "private-key"
    assert "private" not in JsonFormatter().format(record)


def test_failure_after_headers_never_sends_second_response() -> None:
    sent = []

    async def broken(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("private-password")

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    with pytest.raises(RuntimeError, match="after response started") as error:
        asyncio.run(
            RequestLoggingMiddleware(broken)(
                {"type": "http", "method": "GET"},
                receive,
                send,
            )
        )
    assert "private" not in str(error.value)
    assert len(sent) == 1
    assert sent[0]["status"] == 200


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(log_level="VERBOSE")


def test_configuration_reenables_logger_disabled_by_migration_logging() -> None:
    logger.disabled = True
    configure_logging("INFO")
    assert logger.disabled is False
