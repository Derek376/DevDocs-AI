"""Embedding indexing and semantic retrieval endpoints."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.embeddings import EmbeddingProvider
from app.api.documents import SessionDependency
from app.services.search import DocumentNotFoundError, index_document, search_documents

router = APIRouter(tags=["search"])


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider


ProviderDependency = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


class IndexResponse(BaseModel):
    document_id: UUID
    embedded_chunk_count: int
    model: str
    dimensions: int


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20, strict=True)
    document_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=50)
    media_type: Literal["text/plain", "text/markdown", "application/pdf"] | None = None

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must contain non-whitespace text.")
        return value.strip()


class SearchMatch(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    position: int
    source_page: int | None
    text: str
    similarity: float


class SearchResponse(BaseModel):
    model: str
    matches: list[SearchMatch]


@router.post("/documents/{document_id}/index")
async def index(
    document_id: UUID,
    request: Request,
    session: SessionDependency,
    provider: ProviderDependency,
) -> IndexResponse:
    try:
        count = await index_document(
            session,
            document_id,
            provider,
            request.app.state.settings.embedding_batch_size,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IndexResponse(
        document_id=document_id,
        embedded_chunk_count=count,
        model=provider.model_id,
        dimensions=provider.dimensions,
    )


@router.post("/search")
async def search(
    body: SearchRequest,
    request: Request,
    session: SessionDependency,
    provider: ProviderDependency,
) -> SearchResponse:
    settings = request.app.state.settings
    rows = await search_documents(
        session,
        body.question,
        provider,
        limit=body.top_k or settings.retrieval_top_k,
        document_ids=body.document_ids,
        media_type=body.media_type,
        min_similarity=settings.retrieval_min_similarity,
    )
    return SearchResponse(
        model=provider.model_id,
        matches=[
            SearchMatch(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                filename=filename,
                position=chunk.position,
                source_page=chunk.source_page,
                text=chunk.text,
                similarity=similarity,
            )
            for chunk, filename, similarity in rows
        ],
    )
