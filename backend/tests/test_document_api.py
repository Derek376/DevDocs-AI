from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.persistence.database import get_session


@pytest.fixture
def upload_client() -> Iterator[TestClient]:
    app = create_app(Settings(max_upload_bytes=32))

    async def unused_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = unused_session
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "filename, data, media_type, status",
    [
        ("guide.exe", b"text", "application/octet-stream", 415),
        ("guide.txt", b"a" * 33, "text/plain", 413),
        ("guide.txt", b"", "text/plain", 400),
        ("guide.txt", b"\xff", "text/plain", 400),
        ("guide.pdf", b"not pdf", "application/pdf", 400),
        ("guide.txt", b"text", "image/png", 415),
    ],
)
def test_upload_errors_have_useful_http_responses(
    upload_client: TestClient, filename: str, data: bytes, media_type: str, status: int
) -> None:
    response = upload_client.post(
        "/documents", files={"file": (filename, data, media_type)}
    )
    assert response.status_code == status
    assert response.json()["detail"]


def test_missing_file_and_invalid_pagination_return_422(
    upload_client: TestClient,
) -> None:
    assert upload_client.post("/documents").status_code == 422
    assert upload_client.get("/documents?limit=0").status_code == 422
    assert upload_client.get("/documents?offset=-1").status_code == 422
    assert upload_client.get("/documents/not-a-uuid/chunks").status_code == 422


def test_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(ValidationError, match="CHUNK_OVERLAP"):
        Settings(chunk_size=100, chunk_overlap=100)
