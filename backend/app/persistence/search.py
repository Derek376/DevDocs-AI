"""Exact cosine search over compatible, indexed chunks."""

from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import Chunk, Document


async def find_matches(
    session: AsyncSession,
    vector: list[float],
    model_id: str,
    limit: int,
    *,
    document_ids: list[UUID] | None = None,
    media_type: str | None = None,
    min_similarity: float = 0.35,
) -> list[tuple[Chunk, str, float]]:
    # SQL WHERE predicates have no guaranteed evaluation order. Guard distance
    # itself so a similarity predicate cannot evaluate mismatched vector lengths.
    distance = case(
        (
            func.vector_dims(Chunk.embedding) == len(vector),
            Chunk.embedding.cosine_distance(vector),
        ),
        else_=None,
    )
    statement = (
        select(Chunk, Document.filename, distance.label("distance"))
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Document.status == "ready",
            Chunk.embedding.is_not(None),
            Chunk.embedding_model == model_id,
            func.vector_dims(Chunk.embedding) == len(vector),
            distance <= 1.0 - min_similarity,
        )
    )
    # Restrict candidates before ranking/limiting, never widen an empty filter.
    if document_ids is not None:
        statement = statement.where(Document.id.in_(document_ids))
    if media_type is not None:
        statement = statement.where(Document.media_type == media_type)
    rows = await session.execute(statement.order_by(distance, Chunk.id).limit(limit))
    return [
        (chunk, filename, 1.0 - float(distance)) for chunk, filename, distance in rows
    ]
