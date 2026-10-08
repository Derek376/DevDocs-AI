"""Prepare document text off the event loop, then persist it atomically."""

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.persistence.documents import save_document
from app.persistence.models import Document
from app.services.chunking import chunk_sections
from app.services.extraction import TextSection, extract_sections


def prepare_chunks(
    data: bytes, media_type: str, settings: Settings
) -> list[TextSection]:
    sections = extract_sections(data, media_type, settings)
    return chunk_sections(sections, settings.chunk_size, settings.chunk_overlap)


async def ingest_document(
    session: AsyncSession,
    filename: str,
    media_type: str,
    data: bytes,
    settings: Settings,
) -> tuple[Document, int]:
    chunks = await run_in_threadpool(prepare_chunks, data, media_type, settings)
    document = await save_document(
        session,
        filename,
        media_type,
        len(data),
        [(chunk.text, chunk.source_page) for chunk in chunks],
    )
    return document, len(chunks)
