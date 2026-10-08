"""Document writes and bounded listing queries."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import Chunk, Document


async def save_document(
    session: AsyncSession,
    filename: str,
    media_type: str,
    size_bytes: int,
    chunks: list[tuple[str, int | None]],
) -> Document:
    document = Document(
        filename=filename, media_type=media_type, size_bytes=size_bytes, status="ready"
    )
    session.add(document)
    await session.flush()
    session.add_all(
        Chunk(document_id=document.id, position=position, text=text, source_page=page)
        for position, (text, page) in enumerate(chunks)
    )
    await session.commit()
    return document


async def list_documents(
    session: AsyncSession, limit: int, offset: int
) -> list[tuple[Document, int]]:
    result = await session.execute(
        select(Document, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .group_by(Document.id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [(document, count) for document, count in result]


async def list_chunks(
    session: AsyncSession, document_id: UUID, limit: int, offset: int
) -> list[Chunk] | None:
    if await session.get(Document, document_id) is None:
        return None
    result = await session.scalars(
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.position)
        .limit(limit)
        .offset(offset)
    )
    return list(result)
