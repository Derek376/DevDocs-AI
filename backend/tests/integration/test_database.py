"""Real PostgreSQL checks, always run in newly created disposable databases."""

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Engine, create_engine, delete, event, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.ai.embeddings import EmbeddingError
from app.ai.llm import GeneratedAnswer
from app.api.questions import get_llm_provider
from app.api.search import get_embedding_provider
from app.core.config import Settings
from app.main import create_app
from app.persistence.database import get_session
from app.persistence.models import Base, Chunk, Document

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def migrate(engine: Engine, action: str, revision: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        getattr(command, action)(config, revision)


@pytest.fixture
def database_engine() -> Iterator[Engine]:
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL integration tests.")
    url = make_url(raw_url)
    if url.drivername != "postgresql+psycopg":
        pytest.fail("TEST_DATABASE_URL must use postgresql+psycopg.")

    database_name = f"devdocs_test_{uuid4().hex}"
    admin_url = url.set(drivername="postgresql", database="postgres")
    with psycopg.connect(
        admin_url.render_as_string(hide_password=False), autocommit=True
    ) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
        engine = create_engine(url.set(database=database_name))
        try:
            migrate(engine, "upgrade", "head")
            yield engine
        finally:
            engine.dispose()
            admin.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
            )


def settings_for(engine: Engine) -> Settings:
    url = engine.url
    return Settings(
        app_env="test",
        postgres_host=url.host,
        postgres_port=url.port,
        postgres_db=url.database,
        postgres_user=url.username,
        postgres_password=url.password,
    )


def test_migration_round_trip_extension_and_model_agreement(
    database_engine: Engine,
) -> None:
    with database_engine.connect() as connection:
        assert connection.scalar(text("SELECT '[1,2,3]'::vector::text")) == "[1,2,3]"
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002"
        )
        assert (
            compare_metadata(MigrationContext.configure(connection), Base.metadata)
            == []
        )

    migrate(database_engine, "downgrade", "base")
    assert "documents" not in inspect(database_engine).get_table_names()
    assert "chunks" not in inspect(database_engine).get_table_names()
    migrate(database_engine, "upgrade", "head")
    assert "chunks" in inspect(database_engine).get_table_names()


def test_document_chunk_persistence_defaults_and_cascade(
    database_engine: Engine,
) -> None:
    with Session(database_engine) as session:
        document = Document(
            filename="guide.md", media_type="text/markdown", size_bytes=40
        )
        session.add(document)
        session.flush()
        chunk = Chunk(document_id=document.id, position=0, text="Example documentation")
        session.add(chunk)
        session.commit()
        assert document.status == "processing"
        assert document.created_at.tzinfo is not None
        assert chunk.source_page is None
        assert session.scalar(select(Chunk.text)) == "Example documentation"
        session.execute(delete(Document).where(Document.id == document.id))
        session.commit()
        assert session.scalar(select(Chunk.id)) is None


@pytest.mark.parametrize(
    "changes",
    [{"size_bytes": -1}, {"status": "unknown"}, {"filename": ""}],
)
def test_document_constraints_reject_invalid_data(
    database_engine: Engine, changes: dict
) -> None:
    values = {"filename": "guide.txt", "media_type": "text/plain", "size_bytes": 10}
    with Session(database_engine) as session:
        session.add(Document(**(values | changes)))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@pytest.mark.parametrize(
    "case", ["duplicate", "orphan", "negative_position", "empty_text", "bad_page"]
)
def test_chunk_constraints_reject_invalid_data(
    database_engine: Engine, case: str
) -> None:
    with Session(database_engine) as session:
        document = Document(
            filename="guide.txt", media_type="text/plain", size_bytes=10
        )
        session.add(document)
        session.flush()
        session.add(Chunk(document_id=document.id, position=0, text="First chunk"))
        session.commit()
        values = {"document_id": document.id, "position": 1, "text": "Second chunk"}
        changes = {
            "duplicate": {"position": 0},
            "orphan": {"document_id": uuid4()},
            "negative_position": {"position": -1},
            "empty_text": {"text": ""},
            "bad_page": {"source_page": 0},
        }
        session.add(Chunk(**(values | changes[case])))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@pytest.mark.parametrize("commit", [True, False])
def test_request_session_commit_and_rollback(
    database_engine: Engine, commit: bool
) -> None:
    app = create_app(settings_for(database_engine))

    # This route exists only in this test to exercise the actual session dependency.
    @app.post("/test-write")
    async def write(session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
        session.add(
            Document(filename="guide.txt", media_type="text/plain", size_bytes=10)
        )
        await session.flush()
        if not commit:
            raise HTTPException(status_code=400, detail="Simulated failure")
        await session.commit()
        return {"saved": True}

    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.post("/test-write").status_code == (200 if commit else 400)

    with database_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM documents")) == int(commit)


@pytest.mark.parametrize("extension", ["txt", "md", "pdf"])
def test_upload_extract_store_and_inspect(
    database_engine: Engine, make_pdf: Callable, extension: str
) -> None:
    contents = {
        "txt": (b"a" * 1300, "text/plain", 2),
        "md": ("# Guide\n  print('hello')\nUnicode: café".encode(), "text/markdown", 1),
        "pdf": (make_pdf(["Page one", "Page two"]), "application/pdf", 2),
    }
    data, media_type, expected_count = contents[extension]
    with TestClient(create_app(settings_for(database_engine))) as client:
        response = client.post(
            "/documents", files={"file": (f"guide.{extension}", data, media_type)}
        )
        assert response.status_code == 201, response.text
        document = response.json()
        assert document["status"] == "ready"
        assert document["size_bytes"] == len(data)
        assert document["chunk_count"] == expected_count
        assert "error_message" not in document
        assert client.get("/documents").json() == [document]
        chunks = client.get(f"/documents/{document['id']}/chunks").json()
        assert len(chunks) == expected_count
        assert [chunk["position"] for chunk in chunks] == list(range(expected_count))
        assert all(chunk["document_id"] == document["id"] for chunk in chunks)
        if extension == "pdf":
            assert [chunk["source_page"] for chunk in chunks] == [1, 2]
            assert [chunk["text"] for chunk in chunks] == ["Page one", "Page two"]
        elif extension == "md":
            assert "  print('hello')" in chunks[0]["text"]
        else:
            assert [len(chunk["text"]) for chunk in chunks] == [1000, 450]
        assert (
            client.get(f"/documents/{document['id']}/chunks?limit=1").json()
            == chunks[:1]
        )


def test_listing_pagination_missing_documents_and_exact_upload_limit(
    database_engine: Engine,
) -> None:
    settings = settings_for(database_engine)
    settings.max_upload_bytes = 6
    with TestClient(create_app(settings)) as client:
        assert client.get("/documents").json() == []
        for filename in ("one.txt", "two.txt"):
            assert (
                client.post(
                    "/documents", files={"file": (filename, b"123456", "text/plain")}
                ).status_code
                == 201
            )
        documents = client.get("/documents").json()
        assert len(documents) == 2
        assert client.get("/documents?limit=1&offset=1").json() == documents[1:]
        assert client.get(f"/documents/{uuid4()}/chunks").status_code == 404
        response = client.post(
            "/documents", files={"file": ("large.txt", b"1234567", "text/plain")}
        )
        assert response.status_code == 413
        assert len(client.get("/documents").json()) == 2


def test_rejected_extraction_leaves_no_metadata(database_engine: Engine) -> None:
    with TestClient(create_app(settings_for(database_engine))) as client:
        response = client.post(
            "/documents",
            files={"file": ("bad.pdf", b"%PDF-1.7\nbroken", "application/pdf")},
        )
        assert response.status_code == 400
        assert client.get("/documents").json() == []


def test_failed_chunk_write_rolls_back_document_and_returns_safe_error(
    database_engine: Engine,
) -> None:
    def fail_chunk_insert(
        connection, cursor, statement, parameters, context, executemany
    ):
        if statement.startswith("INSERT INTO chunks"):
            raise IntegrityError(statement, {}, Exception("private-database-details"))

    with TestClient(create_app(settings_for(database_engine))) as client:
        async_engine = client.app.state.session_factory.kw["bind"]
        event.listen(
            async_engine.sync_engine, "before_cursor_execute", fail_chunk_insert
        )
        try:
            response = client.post(
                "/documents", files={"file": ("guide.txt", b"Some text", "text/plain")}
            )
        finally:
            event.remove(
                async_engine.sync_engine, "before_cursor_execute", fail_chunk_insert
            )
        assert response.status_code == 503
        assert "private-database-details" not in response.text
        assert client.get("/documents").json() == []

    with database_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM documents")) == 0
        assert connection.scalar(text("SELECT count(*) FROM chunks")) == 0


class KnownVectorProvider:
    """Test geometry with known vectors; this is not a real semantic model."""

    model_id = "test:known-vectors"
    dimensions = 2

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0]
            if "database" in value.lower() or "postgres" in value.lower()
            else [0.0, 1.0]
            for value in texts
        ]


def test_index_and_cosine_search_exclude_unindexed_and_incompatible_chunks(
    database_engine: Engine,
) -> None:
    settings = settings_for(database_engine)
    settings.retrieval_min_similarity = 0.0
    app = create_app(settings)
    app.dependency_overrides[get_embedding_provider] = lambda: KnownVectorProvider()
    with TestClient(app) as client:
        ids = []
        for filename, content in [
            ("db.txt", b"Database transaction documentation"),
            ("ui.txt", b"UI button styles"),
            ("unindexed.txt", b"Database secrets"),
        ]:
            response = client.post(
                "/documents", files={"file": (filename, content, "text/plain")}
            )
            ids.append(response.json()["id"])
        assert (
            client.post("/search", json={"question": "postgres"}).json()["matches"]
            == []
        )
        for document_id in ids[:2]:
            result = client.post(f"/documents/{document_id}/index")
            assert result.status_code == 200, result.text
            assert result.json()["embedded_chunk_count"] == 1
        # Same model with a different vector dimension, and another model, are excluded.
        with Session(database_engine) as session:
            document = session.get(Document, UUID(ids[0]))
            session.add_all(
                [
                    Chunk(
                        document_id=document.id,
                        position=1,
                        text="Wrong dimensions",
                        embedding=[1, 0, 0],
                        embedding_model=KnownVectorProvider.model_id,
                    ),
                    Chunk(
                        document_id=document.id,
                        position=2,
                        text="Wrong model",
                        embedding=[1, 0],
                        embedding_model="test:other-model",
                    ),
                ]
            )
            session.commit()
        matches = client.post("/search", json={"question": "postgres"}).json()[
            "matches"
        ]
        assert [row["document_id"] for row in matches] == ids[:2]
        assert [row["similarity"] for row in matches] == pytest.approx([1, 0])
        assert matches[0]["filename"] == "db.txt"
        assert matches[0]["text"] == "Database transaction documentation"
        assert client.post(f"/documents/{uuid4()}/index").status_code == 404


def test_failed_batch_keeps_previous_embeddings(database_engine: Engine) -> None:
    settings = settings_for(database_engine)
    settings.embedding_batch_size = 1
    app = create_app(settings)
    app.dependency_overrides[get_embedding_provider] = lambda: KnownVectorProvider()
    with TestClient(app) as client:
        response = client.post(
            "/documents",
            files={"file": ("guide.txt", b"database " * 150, "text/plain")},
        )
        document_id = response.json()["id"]
        assert client.post(f"/documents/{document_id}/index").status_code == 200

        class FailingProvider(KnownVectorProvider):
            model_id = "test:new-model"
            calls = 0

            async def embed(self, texts):
                self.calls += 1
                if self.calls == 2:
                    raise EmbeddingError("Simulated second-batch failure.")
                return [[0, 1]]

        provider = FailingProvider()
        app.dependency_overrides[get_embedding_provider] = lambda: provider
        assert client.post(f"/documents/{document_id}/index").status_code == 502
    with Session(database_engine) as session:
        chunks = session.scalars(
            select(Chunk).where(Chunk.document_id == UUID(document_id))
        ).all()
        assert len(chunks) == 2
        assert all(
            chunk.embedding_model == KnownVectorProvider.model_id for chunk in chunks
        )
        assert all(list(chunk.embedding) == [1, 0] for chunk in chunks)


def test_embedding_migration_preserves_existing_text(database_engine: Engine) -> None:
    migrate(database_engine, "downgrade", "0001")
    document_id, chunk_id = uuid4(), uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (id, filename, media_type, size_bytes) "
                "VALUES (:id, 'old.txt', 'text/plain', 3)"
            ),
            {"id": document_id},
        )
        connection.execute(
            text(
                "INSERT INTO chunks (id, document_id, position, text) "
                "VALUES (:id, :document_id, 0, 'old')"
            ),
            {"id": chunk_id, "document_id": document_id},
        )
    migrate(database_engine, "upgrade", "head")
    with Session(database_engine) as session:
        chunk = session.get(Chunk, chunk_id)
        assert chunk.text == "old"
        assert chunk.embedding is None
        assert chunk.embedding_model is None


def test_rag_pipeline_returns_answer_and_real_pdf_source_reference(
    database_engine: Engine, make_pdf: Callable
) -> None:
    import json

    class SourceUsingLLM:
        model_id = "test:llm"

        async def generate(self, system_prompt, user_prompt):
            sources = json.loads(user_prompt)["sources"]
            assert (
                sources[0]["text"] == "Database changes can be undone using rollback."
            )
            return GeneratedAnswer(answer="Use rollback [S1].", citation_labels=["S1"])

    app = create_app(settings_for(database_engine))
    app.dependency_overrides[get_embedding_provider] = lambda: KnownVectorProvider()
    app.dependency_overrides[get_llm_provider] = lambda: SourceUsingLLM()
    with TestClient(app) as client:
        response = client.post(
            "/documents",
            files={
                "file": (
                    "guide.pdf",
                    make_pdf(["Database changes can be undone using rollback."]),
                    "application/pdf",
                )
            },
        )
        document_id = response.json()["id"]
        assert client.post(f"/documents/{document_id}/index").status_code == 200
        response = client.post(
            "/questions", json={"question": "How do I undo database changes?"}
        )
        assert response.status_code == 200, response.text
        answer = response.json()
        assert answer["status"] == "answered"
        assert answer["answer"] == "Use rollback [S1]."
        chunk = client.get(f"/documents/{document_id}/chunks").json()[0]
        citation = answer["citations"][0]
        assert citation["chunk_id"] == chunk["id"]
        assert citation["document_id"] == document_id
        assert citation["text"] == chunk["text"]
        assert citation["filename"] == "guide.pdf"
        assert citation["source_page"] == 1
        assert citation["label"] == "S1"
        assert client.post("/questions", json={"question": " "}).status_code == 422


def test_empty_corpus_does_not_call_llm(database_engine: Engine) -> None:
    class NeverCalledLLM:
        model_id = "test:llm"

        async def generate(self, system_prompt, user_prompt):
            raise AssertionError("LLM should not be called without sources")

    app = create_app(settings_for(database_engine))
    app.dependency_overrides[get_embedding_provider] = lambda: KnownVectorProvider()
    app.dependency_overrides[get_llm_provider] = lambda: NeverCalledLLM()
    with TestClient(app) as client:
        result = client.post("/questions", json={"question": "How does this work?"})
        assert result.status_code == 200
        assert result.json()["status"] == "insufficient_evidence"
        assert result.json()["citations"] == []


def test_hallucinated_citation_is_not_returned_as_an_answer(
    database_engine: Engine,
) -> None:
    class InvalidCitationLLM:
        model_id = "test:llm"

        async def generate(self, system_prompt, user_prompt):
            return GeneratedAnswer(
                answer="Use rollback [S99].", citation_labels=["S99"]
            )

    app = create_app(settings_for(database_engine))
    app.dependency_overrides[get_embedding_provider] = lambda: KnownVectorProvider()
    app.dependency_overrides[get_llm_provider] = lambda: InvalidCitationLLM()
    with TestClient(app) as client:
        document_id = client.post(
            "/documents",
            files={
                "file": ("guide.txt", b"Database rollback instructions.", "text/plain")
            },
        ).json()["id"]
        assert client.post(f"/documents/{document_id}/index").status_code == 200
        result = client.post("/questions", json={"question": "database rollback"})
        assert result.status_code == 502
        assert "answer" not in result.json()
        assert "citations" in result.json()["detail"]


def test_metadata_filters_apply_before_limit_and_can_return_no_evidence(
    database_engine: Engine,
) -> None:
    app = create_app(settings_for(database_engine))
    app.dependency_overrides[get_embedding_provider] = lambda: KnownVectorProvider()

    class SourceUsingLLM:
        model_id = "test:llm"

        async def generate(self, system_prompt, user_prompt):
            import json

            sources = json.loads(user_prompt)["sources"]
            assert len(sources) == 1
            assert sources[0]["filename"] == "selected.md"
            return GeneratedAnswer(
                answer="Selected documentation [S1].", citation_labels=["S1"]
            )

    app.dependency_overrides[get_llm_provider] = lambda: SourceUsingLLM()
    with TestClient(app) as client:
        ids = []
        for filename, content, media_type in [
            ("other.txt", b"Database transaction documentation", "text/plain"),
            ("selected.md", b"Database rollback guide", "text/markdown"),
            ("weak.txt", b"UI button styles", "text/plain"),
        ]:
            upload = client.post(
                "/documents", files={"file": (filename, content, media_type)}
            )
            assert upload.status_code == 201
            ids.append(upload.json()["id"])
            assert client.post(f"/documents/{ids[-1]}/index").status_code == 200
        # The excluded document is closer than the selected one. Post-limit filtering
        # would lose the selected match instead of returning it.
        with Session(database_engine) as session:
            chunk = session.scalar(
                select(Chunk).where(Chunk.document_id == UUID(ids[1]))
            )
            chunk.embedding = [0.8, 0.6]
            session.commit()
        query = {
            "question": "database",
            "top_k": 1,
            "document_ids": [ids[1]],
            "media_type": "text/markdown",
        }
        matches = client.post("/search", json=query).json()["matches"]
        assert [match["document_id"] for match in matches] == [ids[1]]
        assert matches[0]["similarity"] == pytest.approx(0.8)
        result = client.post("/questions", json=query)
        assert result.status_code == 200, result.text
        assert result.json()["citations"][0]["document_id"] == ids[1]
        assert (
            client.post("/search", json={"question": "database", "top_k": 1}).json()[
                "matches"
            ][0]["document_id"]
            == ids[0]
        )
        for options in [
            {"document_ids": [ids[1]], "media_type": "application/pdf"},
            {"document_ids": [str(uuid4())]},
            {"document_ids": [ids[2]]},
        ]:
            result = client.post("/questions", json={"question": "database", **options})
            assert result.status_code == 200, result.text
            assert result.json()["status"] == "insufficient_evidence"
            assert result.json()["citations"] == []


def test_rag_fetches_past_duplicates_to_fill_useful_source_slots(
    database_engine: Engine,
) -> None:
    import json

    app = create_app(settings_for(database_engine))
    app.dependency_overrides[get_embedding_provider] = lambda: KnownVectorProvider()

    class CheckingLLM:
        model_id = "test:llm"

        async def generate(self, system_prompt, user_prompt):
            sources = json.loads(user_prompt)["sources"]
            assert [source["text"] for source in sources] == [
                "Database transaction overview.",
                "Database rollback instructions.",
            ]
            assert [source["label"] for source in sources] == ["S1", "S2"]
            return GeneratedAnswer(
                answer="Rollback instructions [S2].", citation_labels=["S2"]
            )

    app.dependency_overrides[get_llm_provider] = lambda: CheckingLLM()
    with TestClient(app) as client:
        ids = []
        for index, content in enumerate(
            [
                b"Database transaction overview.",
                b"Database transaction overview.",
                b"Database rollback instructions.",
            ]
        ):
            upload = client.post(
                "/documents",
                files={"file": (f"doc-{index}.txt", content, "text/plain")},
            )
            ids.append(upload.json()["id"])
            assert client.post(f"/documents/{ids[-1]}/index").status_code == 200
        with Session(database_engine) as session:
            for document_id, vector in zip(
                ids, [[1, 0], [0.99, 0.1], [0.8, 0.6]], strict=True
            ):
                chunk = session.scalar(
                    select(Chunk).where(Chunk.document_id == UUID(document_id))
                )
                chunk.embedding = vector
            session.commit()
        result = client.post("/questions", json={"question": "database", "top_k": 2})
        assert result.status_code == 200, result.text
        assert result.json()["citations"][0]["document_id"] == ids[2]
        assert result.json()["citations"][0]["label"] == "S2"
