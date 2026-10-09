import pytest

from app.ai.embeddings import EmbeddingError, validate_vectors


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
