import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.ai.llm import GeneratedAnswer, LLMError
from app.persistence.models import Chunk
from app.services.rag import (
    INSUFFICIENT_EVIDENCE,
    SYSTEM_PROMPT,
    answer_question,
    build_context,
    resolve_citations,
)


def source_rows():
    document_id = uuid4()
    return [
        (
            Chunk(
                id=uuid4(),
                document_id=document_id,
                position=0,
                text="rollback",
                source_page=2,
            ),
            "guide.pdf",
            0.8,
        ),
        (
            Chunk(
                id=uuid4(),
                document_id=document_id,
                position=1,
                text="commit",
                source_page=3,
            ),
            "guide.pdf",
            0.7,
        ),
    ]


def test_context_budget_retains_provenance_and_marks_truncated_excerpts() -> None:
    rows = source_rows()
    sources = build_context(rows, max_characters=10)
    assert [source.text for source in sources] == ["rollback", "co"]
    assert [source.label for source in sources] == ["S1", "S2"]
    assert [source.truncated for source in sources] == [False, True]
    assert sources[0].chunk_id == rows[0][0].id
    assert sources[0].source_page == 2


@pytest.mark.parametrize(
    "answer, labels",
    [
        ("Invented [S99].", ["S99"]),
        ("Unmarked answer.", ["S1"]),
        ("Mismatch [S2].", ["S1"]),
        ("Answer [S1] and invented [S99].", ["S1"]),
    ],
)
def test_invalid_citations_are_rejected(answer: str, labels: list[str]) -> None:
    with pytest.raises(LLMError, match="citations"):
        resolve_citations(
            GeneratedAnswer(answer=answer, citation_labels=labels),
            build_context(source_rows()),
        )


def test_valid_citations_are_resolved_and_deduplicated() -> None:
    sources = build_context(source_rows())
    reply = GeneratedAnswer(answer="Use rollback [S1].", citation_labels=["S1", "S1"])
    assert resolve_citations(reply, sources) == sources[:1]


@pytest.mark.parametrize("case", ["answer", "no_sources", "uncited"])
def test_rag_orchestration_prompt_boundary_and_decline(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    rows = source_rows() if case != "no_sources" else []
    retrieve = AsyncMock(return_value=rows)
    monkeypatch.setattr("app.services.rag.search_documents", retrieve)
    session = AsyncMock()
    embeddings = AsyncMock(model_id="test:embeddings")
    llm = AsyncMock(model_id="test:llm")
    llm.generate.return_value = GeneratedAnswer(
        answer="Use rollback [S1]."
        if case == "answer"
        else "Unsupported model assertion",
        citation_labels=["S1"] if case == "answer" else [],
    )
    result = asyncio.run(
        answer_question(session, "How do I undo changes?", embeddings, llm)
    )
    session.rollback.assert_awaited_once()
    retrieve.assert_awaited_once_with(
        session,
        "How do I undo changes?",
        embeddings,
        limit=15,
        document_ids=None,
        media_type=None,
        min_similarity=0.35,
    )
    if case == "no_sources":
        llm.generate.assert_not_awaited()
    else:
        system, user = llm.generate.call_args.args
        assert system == SYSTEM_PROMPT
        prompt_data = json.loads(user)
        assert prompt_data["question"] == "How do I undo changes?"
        assert prompt_data["sources"][0]["text"] == "rollback"
        assert "untrusted" in system
    if case == "answer":
        assert result.status == "answered"
        assert result.citations[0].chunk_id == rows[0][0].id
    else:
        assert result.status == "insufficient_evidence"
        assert result.answer == INSUFFICIENT_EVIDENCE
        assert result.citations == []
