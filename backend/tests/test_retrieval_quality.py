import asyncio
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.persistence.database import get_session
from app.persistence.models import Chunk
from app.services.rag import (
    INSUFFICIENT_EVIDENCE,
    RagResult,
    answer_question,
    build_context,
)


def row(text, *, score=0.8, document_id=None, position=0, page=None):
    return (
        Chunk(
            id=uuid4(),
            document_id=document_id or uuid4(),
            position=position,
            text=text,
            source_page=page,
        ),
        "guide.md",
        score,
    )


def test_duplicate_excerpts_do_not_consume_source_slots_or_budget() -> None:
    rows = [row("BEGIN;\nROLLBACK;\n"), row("BEGIN;\r\nROLLBACK;\r\n"), row("COMMIT;")]
    sources = build_context(rows, top_k=2)
    assert [source.chunk_id for source in sources] == [rows[0][0].id, rows[2][0].id]
    assert [source.label for source in sources] == ["S1", "S2"]


def test_small_code_differences_are_preserved() -> None:
    rows = [row("return True"), row("return true"), row("    return True")]
    assert len(build_context(rows)) == 3


def test_exact_adjacent_overlap_is_trimmed_with_provenance_retained() -> None:
    shared = " ".join(f"parameter_{index}" for index in range(12))
    document_id = uuid4()
    rows = [
        row("Start. " + shared, document_id=document_id, position=0, page=1),
        row(shared + " End.", document_id=document_id, position=1, page=1),
    ]
    sources = build_context(rows)
    assert sources[1].text == " End."
    assert sources[1].chunk_id == rows[1][0].id
    assert sources[1].source_page == 1
    assert sources[1].truncated is True
    assert sources[1].text in rows[1][0].text


@pytest.mark.parametrize(
    "case", ["other_document", "other_page", "non_adjacent", "reverse_order"]
)
def test_overlap_cleanup_does_not_merge_unrelated_boundaries(case) -> None:
    shared = " ".join(f"parameter_{index}" for index in range(12))
    document_id = uuid4()
    left = row("Start. " + shared, document_id=document_id, position=0, page=1)
    right = row(shared + " End.", document_id=document_id, position=1, page=1)
    if case == "other_document":
        right[0].document_id = uuid4()
    elif case == "other_page":
        right[0].source_page = 2
    elif case == "non_adjacent":
        right[0].position = 3
    rows = [right, left] if case == "reverse_order" else [left, right]
    assert [source.text for source in build_context(rows)] == [
        item[0].text for item in rows
    ]


def test_threshold_top_k_and_budget_apply_after_cleanup() -> None:
    rows = [
        row("weak", score=0.2),
        row("first", score=0.9),
        row("first", score=0.8),
        row("second", score=0.7),
    ]
    assert [source.text for source in build_context(rows, top_k=1)] == ["first"]
    sources = build_context(rows, top_k=2, max_characters=8)
    assert [source.text for source in sources] == ["first", "sec"]
    assert sources[-1].truncated
    assert build_context([row("at cutoff", score=0.35)], min_similarity=0.35)


def test_only_weak_evidence_skips_generation(monkeypatch) -> None:
    retrieve = AsyncMock(return_value=[row("unrelated", score=0.1)])
    monkeypatch.setattr("app.services.rag.search_documents", retrieve)
    session = AsyncMock()
    embeddings = AsyncMock(model_id="test:embeddings")
    llm = AsyncMock(model_id="test:llm")
    result = asyncio.run(answer_question(session, "Question", embeddings, llm, top_k=2))
    llm.generate.assert_not_awaited()
    session.rollback.assert_awaited_once()
    assert result.status == "insufficient_evidence"
    assert result.answer == INSUFFICIENT_EVIDENCE
    assert result.citations == []
    assert retrieve.call_args.kwargs["limit"] == 6


@pytest.mark.parametrize(
    "changes",
    [
        {"retrieval_top_k": 0},
        {"retrieval_top_k": 21},
        {"retrieval_min_similarity": -0.1},
        {"retrieval_min_similarity": 1.1},
        {"retrieval_min_similarity": float("nan")},
    ],
)
def test_invalid_retrieval_configuration_is_rejected(changes) -> None:
    with pytest.raises(ValidationError):
        Settings(**changes)


@pytest.mark.parametrize("path", ["/search", "/questions"])
@pytest.mark.parametrize(
    "options",
    [
        {"top_k": 0},
        {"top_k": 21},
        {"top_k": True},
        {"top_k": "5"},
        {"top_k": 2.5},
        {"document_ids": []},
        {"document_ids": ["bad-id"]},
        {"document_ids": [str(uuid4()) for _ in range(51)]},
        {"media_type": "text/html"},
        {"unexpected": True},
    ],
)
def test_invalid_retrieval_options_return_422(
    client: TestClient, path, options
) -> None:
    async def unused_session():
        yield None

    client.app.dependency_overrides[get_session] = unused_session
    assert (
        client.post(path, json={"question": "Question", **options}).status_code == 422
    )


@pytest.mark.parametrize("path", ["/search", "/questions"])
def test_routes_forward_filters_and_use_configured_or_requested_top_k(
    client, monkeypatch, path
) -> None:
    async def unused_session():
        yield None

    client.app.dependency_overrides[get_session] = unused_session
    client.app.state.settings.retrieval_top_k = 3
    client.app.state.settings.retrieval_min_similarity = 0.6
    target = (
        "app.api.search.search_documents"
        if path == "/search"
        else "app.api.questions.answer_question"
    )
    result = (
        []
        if path == "/search"
        else RagResult(
            INSUFFICIENT_EVIDENCE,
            "insufficient_evidence",
            [],
            "test:llm",
            "test:embeddings",
        )
    )
    service = AsyncMock(return_value=result)
    monkeypatch.setattr(target, service)
    document_id = uuid4()
    key = "limit" if path == "/search" else "top_k"
    response = client.post(
        path,
        json={
            "question": "Question",
            "document_ids": [str(document_id)],
            "media_type": "application/pdf",
        },
    )
    assert response.status_code == 200
    assert service.call_args.kwargs[key] == 3
    assert service.call_args.kwargs["document_ids"] == [UUID(str(document_id))]
    assert service.call_args.kwargs["media_type"] == "application/pdf"
    assert service.call_args.kwargs["min_similarity"] == 0.6
    assert (
        client.post(path, json={"question": "Question", "top_k": 1}).status_code == 200
    )
    assert service.call_args.kwargs[key] == 1
