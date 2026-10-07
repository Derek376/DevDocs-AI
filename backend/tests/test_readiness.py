from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.persistence.database import get_session


def test_unconfigured_database_returns_useful_503(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 503
    assert "Database is not configured" in response.json()["detail"]
    assert client.get("/health").status_code == 200


def test_database_error_returns_503_without_internal_details(
    client: TestClient,
) -> None:
    async def failing_session():
        session = AsyncMock()
        session.execute.side_effect = OperationalError(
            "SELECT 1", {}, Exception("internal-password-and-host")
        )
        yield session

    client.app.dependency_overrides[get_session] = failing_session
    try:
        response = client.get("/ready")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "Database is unavailable" in response.json()["detail"]
    assert "internal-password-and-host" not in response.text
