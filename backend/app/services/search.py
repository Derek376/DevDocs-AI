"""Index existing documents and retrieve source evidence; no answer generation."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import EmbeddingProvider, validate_vectors
from app.persistence.models import Chunk, Document
from app.persistence.search import find_matches


class DocumentNotFoundError(ValueError):
    pass


async def index_document(
    session: AsyncSession,
    document_id: UUID,
    provider: EmbeddingProvider,
    batch_size: int,
) -> int:
    document = await session.get(Document, document_id)
    if document is None:
        raise DocumentNotFoundError("Document not found.")
    chunks = list(
        await session.scalars(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.position)
        )
    )
    texts = [chunk.text for chunk in chunks]
    chunk_ids = [chunk.id for chunk in chunks]
    # Snapshot values first: rollback expires ORM attributes.
    await session.rollback()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors.extend(
            validate_vectors(
                await provider.embed(batch), len(batch), provider.dimensions
            )
        )
    # All batches must succeed before changing any existing embeddings.
    if chunks:
        await session.execute(
            update(Chunk),
            [
                {
                    "id": chunk_id,
                    "embedding": vector,
                    "embedding_model": provider.model_id,
                }
                for chunk_id, vector in zip(chunk_ids, vectors, strict=True)
            ],
        )
    await session.commit()
    return len(chunks)


async def search_documents(
    session: AsyncSession,
    question: str,
    provider: EmbeddingProvider,
    limit: int,
    *,
    document_ids: list[UUID] | None = None,
    media_type: str | None = None,
    min_similarity: float = 0.35,
) -> list[tuple[Chunk, str, float]]:
    vectors = validate_vectors(await provider.embed([question]), 1, provider.dimensions)
    return await find_matches(
        session,
        vectors[0],
        provider.model_id,
        limit,
        document_ids=document_ids,
        media_type=media_type,
        min_similarity=min_similarity,
    )
