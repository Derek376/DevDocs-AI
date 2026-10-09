"""Opt-in live evaluation of production services in an owned disposable database."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.embeddings import EmbeddingError, EmbeddingProvider
from app.ai.llm import GeneratedAnswer, LLMError, LLMProvider
from app.ai.ollama import OllamaEmbeddingProvider, OllamaLLMProvider
from app.ai.openai import OpenAILLMProvider
from app.core.config import Settings
from app.persistence.database import create_database_engine
from app.services.ingestion import ingest_document
from app.services.rag import MAX_CONTEXT_CHARACTERS, SYSTEM_PROMPT, answer_question
from app.services.search import index_document
from evals.dataset import Dataset, load_dataset
from evals.metrics import retrieval_metrics

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class RecordingLLM:
    """Observe the exact prompt context, including context for refused answers."""

    def __init__(self, delegate: LLMProvider) -> None:
        self.delegate = delegate
        self.model_id = delegate.model_id
        self.context: list[dict] = []

    async def generate(self, system_prompt: str, user_prompt: str) -> GeneratedAnswer:
        self.context = json.loads(user_prompt)["sources"]
        return await self.delegate.generate(system_prompt, user_prompt)


@contextmanager
def disposable_database(settings: Settings) -> Iterator[Settings]:
    # Never accept a target database name: only this fresh, owned name is dropped.
    name = f"devdocs_eval_{uuid4().hex}"
    admin_url = settings.database_url.set(drivername="postgresql", database="postgres")
    with psycopg.connect(
        admin_url.render_as_string(hide_password=False),
        autocommit=True,
        connect_timeout=5,
    ) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            isolated = settings.model_copy(update={"postgres_db": name})
            engine = create_engine(isolated.database_url)
            try:
                config = Config(str(BACKEND_ROOT / "alembic.ini"))
                with engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.upgrade(config, "head")
            finally:
                engine.dispose()
            yield isolated
        finally:
            # FORCE closes only connections to the database created by this run.
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


async def evaluate(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    dataset: Dataset,
    corpus: dict[str, bytes],
    embeddings: EmbeddingProvider,
    llm: LLMProvider,
) -> list[dict]:
    ids = {}
    async with sessions() as session:
        for filename, data in corpus.items():
            document, _ = await ingest_document(
                session, filename, "text/markdown", data, settings
            )
            ids[filename] = document.id
            await index_document(
                session, document.id, embeddings, settings.embedding_batch_size
            )
    results = []
    for case in dataset.cases:
        recorder = RecordingLLM(llm)
        started = perf_counter()
        row = {
            "case_id": case.id,
            "question": case.question,
            "expected_status": case.expected_status,
            "reference_answer": case.reference_answer,
            "gold_evidence": [gold.model_dump() for gold in case.evidence],
            "document_filter": case.documents,
            "answer": "",
            "citations": [],
            "error": None,
        }
        async with sessions() as session:
            try:
                result = await answer_question(
                    session,
                    case.question,
                    embeddings,
                    recorder,
                    top_k=settings.retrieval_top_k,
                    min_similarity=settings.retrieval_min_similarity,
                    document_ids=[ids[name] for name in case.documents]
                    if case.documents is not None
                    else None,
                )
                row.update(
                    status=result.status,
                    answer=result.answer,
                    citations=json.loads(
                        json.dumps(
                            [asdict(source) for source in result.citations], default=str
                        )
                    ),
                )
            except (EmbeddingError, LLMError) as exc:
                row.update(status="error", error=str(exc))
            except SQLAlchemyError:
                row.update(status="error", error="Database operation failed.")
        row.update(
            context=recorder.context,
            elapsed_seconds=round(perf_counter() - started, 3),
            # Without a completed retrieval we cannot assume an empty context.
            retrieval=retrieval_metrics(case, recorder.context)
            if row["status"] != "error" or recorder.context
            else None,
        )
        results.append(row)
        print(f"{case.id}: {row['status']}", flush=True)
    return results


async def run_live(path: Path, settings: Settings) -> dict:
    dataset, corpus, fingerprint = load_dataset(path)
    report = {
        "schema_version": 1,
        "run_id": uuid4().hex,
        "started_at": datetime.now(UTC).isoformat(),
        "dataset_version": dataset.version,
        "dataset_sha256": fingerprint,
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        # Explicit allowlist: never serialize Settings or connection URLs.
        "config": {
            "llm_model": f"{settings.llm_provider}:{settings.llm_model}",
            "embedding_model": f"ollama:{settings.embedding_model}",
            "embedding_dimensions": settings.embedding_dimensions,
            "top_k": settings.retrieval_top_k,
            "min_similarity": settings.retrieval_min_similarity,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "max_context_characters": MAX_CONTEXT_CHARACTERS,
        },
    }
    with disposable_database(settings) as isolated:
        engine = create_database_engine(isolated)
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                embeddings = OllamaEmbeddingProvider(settings, client)
                llm = (
                    OpenAILLMProvider(settings, client)
                    if settings.llm_provider == "openai"
                    else OllamaLLMProvider(settings, client)
                )
                report["cases"] = await evaluate(
                    async_sessionmaker(engine, expire_on_commit=False),
                    isolated,
                    dataset,
                    corpus,
                    embeddings,
                    llm,
                )
        finally:
            await engine.dispose()
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["database_removed"] = True
    return report
