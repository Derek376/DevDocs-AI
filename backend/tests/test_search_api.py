from fastapi.testclient import TestClient

from app.ai.embeddings import EmbeddingError
from app.api.search import get_embedding_provider
from app.persistence.database import get_session


def test_invalid_search_input_is_rejected(client: TestClient) -> None:
    async def unused_session():
        yield None

    client.app.dependency_overrides[get_session] = unused_session
    for body in [
        {"question": " "},
        {"question": "x", "top_k": 0},
        {"question": "x", "top_k": 21},
        {"question": "x" * 2001},
    ]:
        assert client.post("/search", json=body).status_code == 422


def test_embedding_failure_returns_useful_502(client: TestClient) -> None:
    class UnavailableProvider:
        model_id = "test:model"
        dimensions = 2

        async def embed(self, texts):
            raise EmbeddingError("Embedding provider is unavailable.")

    async def unused_session():
        yield None

    client.app.dependency_overrides[get_session] = unused_session
    client.app.dependency_overrides[get_embedding_provider] = lambda: (
        UnavailableProvider()
    )
    response = client.post("/search", json={"question": "How does this work?"})
    assert response.status_code == 502
    assert "unavailable" in response.json()["detail"]
