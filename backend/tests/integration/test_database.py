"""Real PostgreSQL checks, always run in newly created disposable databases."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Engine, create_engine, delete, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

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
            connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
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
