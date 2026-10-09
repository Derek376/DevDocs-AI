import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.ai.llm import GeneratedAnswer, LLMError
from app.ai.tools import ToolArguments, ToolCall
from app.core.config import Settings
from app.persistence.models import Chunk, Document
from app.services.agent import SUMMARY_CHUNK_LIMIT, run_agent
from app.services.search import DocumentNotFoundError


def setup(monkeypatch, tool, *, selected=True, count=1, status="ready"):
    document_id = uuid4() if selected else None
    document = Document(
        id=document_id,
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=50,
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    metadata = AsyncMock(return_value=(document, count))
    monkeypatch.setattr("app.services.agent.repository.get_document_metadata", metadata)
    rows = [
        (
            Chunk(
                id=uuid4(),
                document_id=document_id or uuid4(),
                position=0,
                text="Use ROLLBACK to discard uncommitted changes.",
                source_page=None,
            ),
            "guide.md",
            0.9,
        )
    ]
    chunks = AsyncMock(return_value=[rows[0][0]])
    retrieve = AsyncMock(return_value=rows)
    monkeypatch.setattr("app.services.agent.repository.list_chunks", chunks)
    monkeypatch.setattr("app.services.agent.search_documents", retrieve)
    session = AsyncMock()
    agent = AsyncMock(model_id="test:agent")
    agent.choose_tool.return_value = ToolCall(
        tool, ToolArguments(document_id=document_id), "call-test"
    )
    agent.complete_tool.return_value = GeneratedAnswer(
        answer="Use ROLLBACK [S1].", citation_labels=["S1"]
    )
    embeddings = AsyncMock(model_id="test:embedding")
    return document_id, metadata, chunks, retrieve, session, agent, embeddings


@pytest.mark.parametrize(
    "tool",
    ["retrieve_documentation", "inspect_document_metadata", "summarize_document"],
)
def test_tools_execute_only_the_selected_operation_and_preserve_provenance(
    monkeypatch, tool
):
    doc_id, metadata, chunks, retrieve, session, agent, embeddings = setup(
        monkeypatch, tool
    )

    async def choose(*args):
        session.rollback.assert_awaited_once()
        return ToolCall(tool, ToolArguments(document_id=doc_id), "call-test")

    agent.choose_tool.side_effect = choose

    async def complete(*args):
        assert session.rollback.await_count == 2
        return GeneratedAnswer(answer="Use ROLLBACK [S1].", citation_labels=["S1"])

    agent.complete_tool.side_effect = complete
    result = asyncio.run(
        run_agent(session, "Question", doc_id, embeddings, agent, Settings())
    )
    assert result.tool == tool
    if tool == "inspect_document_metadata":
        assert result.status == "metadata"
        assert result.document.chunk_count == 1
        assert not result.citations
        chunks.assert_not_awaited()
        retrieve.assert_not_awaited()
        agent.complete_tool.assert_not_awaited()
    else:
        assert result.status == "answered"
        assert result.citations[0].document_id == doc_id
        if tool == "summarize_document":
            retrieve.assert_not_awaited()
            chunks.assert_awaited_once_with(session, doc_id, SUMMARY_CHUNK_LIMIT, 0)
            assert result.citations[0].similarity is None
        else:
            chunks.assert_not_awaited()
            assert retrieve.call_args.kwargs["document_ids"] == [doc_id]
            assert result.citations[0].similarity == 0.9
    # Retrieval itself is substituted in this unit test.
    embeddings.embed.assert_not_awaited()


@pytest.mark.parametrize("tool", ["inspect_document_metadata", "summarize_document"])
def test_missing_selection_requests_selection_without_db_or_generation(
    monkeypatch, tool
):
    doc_id, metadata, chunks, retrieve, session, agent, embeddings = setup(
        monkeypatch, tool, selected=False
    )
    result = asyncio.run(
        run_agent(session, "Question", doc_id, embeddings, agent, Settings())
    )
    assert result.status == "selection_required"
    metadata.assert_not_awaited()
    chunks.assert_not_awaited()
    retrieve.assert_not_awaited()
    agent.complete_tool.assert_not_awaited()


@pytest.mark.parametrize("scope", ["other_document", "widen", "unknown_tool"])
def test_model_cannot_change_user_scope_or_request_other_tools(monkeypatch, scope):
    doc_id, metadata, chunks, retrieve, session, agent, embeddings = setup(
        monkeypatch, "summarize_document"
    )
    agent.choose_tool.return_value = ToolCall(
        "run_shell" if scope == "unknown_tool" else "retrieve_documentation",
        ToolArguments(document_id=uuid4() if scope == "other_document" else None),
        "call-test",
    )
    with pytest.raises(LLMError, match="invalid tool or document scope"):
        asyncio.run(
            run_agent(session, "Question", doc_id, embeddings, agent, Settings())
        )
    chunks.assert_not_awaited()
    retrieve.assert_not_awaited()
    agent.complete_tool.assert_not_awaited()


@pytest.mark.parametrize("case", ["no_sources", "uncited", "bad_citation"])
def test_agent_uses_existing_evidence_and_citation_contract(monkeypatch, case):
    doc_id, metadata, chunks, retrieve, session, agent, embeddings = setup(
        monkeypatch, "retrieve_documentation"
    )
    if case == "no_sources":
        retrieve.return_value = []
    else:
        agent.complete_tool.return_value = GeneratedAnswer(
            answer="Invented [S99]",
            citation_labels=["S99"] if case == "bad_citation" else [],
        )
    if case == "bad_citation":
        with pytest.raises(LLMError, match="citations"):
            asyncio.run(
                run_agent(session, "Question", doc_id, embeddings, agent, Settings())
            )
    else:
        result = asyncio.run(
            run_agent(session, "Question", doc_id, embeddings, agent, Settings())
        )
        assert result.status == "insufficient_evidence"
        assert not result.citations
        if case == "no_sources":
            agent.complete_tool.assert_not_awaited()


@pytest.mark.parametrize("reason", ["chunk_limit", "character_limit", "exact_budget"])
def test_summary_explicitly_marks_incomplete_document_coverage(monkeypatch, reason):
    doc_id, metadata, chunks, retrieve, session, agent, embeddings = setup(
        monkeypatch, "summarize_document", count=6 if reason == "chunk_limit" else 1
    )
    if reason == "character_limit":
        chunks.return_value[0].text = "a" * 6000
    if reason == "exact_budget":
        chunks.return_value[0].text = "a" * 5000
        chunks.return_value.append(
            Chunk(
                id=uuid4(),
                document_id=doc_id,
                position=1,
                text="Later evidence",
                source_page=None,
            )
        )
    result = asyncio.run(
        run_agent(session, "Summarize this", doc_id, embeddings, agent, Settings())
    )
    assert result.context_truncated is True
    output = agent.complete_tool.call_args.args[2]
    assert output["context_truncated"] is True
    assert sum(len(s["text"]) for s in output["sources"]) <= 5000
    assert "partial summary" in agent.complete_tool.call_args.args[3]


def test_missing_document_does_not_call_model(monkeypatch):
    doc_id, metadata, chunks, retrieve, session, agent, embeddings = setup(
        monkeypatch, "summarize_document"
    )
    metadata.return_value = None
    with pytest.raises(DocumentNotFoundError):
        asyncio.run(
            run_agent(session, "Question", doc_id, embeddings, agent, Settings())
        )
    agent.choose_tool.assert_not_awaited()


def test_nonready_document_is_not_summarized(monkeypatch):
    doc_id, metadata, chunks, retrieve, session, agent, embeddings = setup(
        monkeypatch, "summarize_document", status="failed"
    )
    result = asyncio.run(
        run_agent(session, "Question", doc_id, embeddings, agent, Settings())
    )
    assert result.status == "insufficient_evidence"
    chunks.assert_not_awaited()
    agent.complete_tool.assert_not_awaited()
