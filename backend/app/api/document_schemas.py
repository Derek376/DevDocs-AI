"""Public document metadata and source chunk contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    media_type: str
    size_bytes: int
    status: Literal["processing", "ready", "failed"]
    created_at: datetime
    updated_at: datetime
    chunk_count: int = 0


class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    position: int
    text: str
    source_page: int | None
