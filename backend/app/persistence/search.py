"""Exact cosine search over compatible, indexed chunks."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import Chunk, Document


async def find_matches(
    session: AsyncSession, vector: list[float], model_id: str, limit: int
) -> list[tuple[Chunk, str, float]]:
    distance = Chunk.embedding.cosine_distance(vector)
    rows = await session.execute(
        select(Chunk, Document.filename, distance.label("distance"))
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Document.status == "ready",
            Chunk.embedding.is_not(None),
            Chunk.embedding_model == model_id,
            func.vector_dims(Chunk.embedding) == len(vector),
        )
        .order_by(distance, Chunk.id)
        .limit(limit)
    )
    return [
        (chunk, filename, 1.0 - float(distance)) for chunk, filename, distance in rows
    ]
