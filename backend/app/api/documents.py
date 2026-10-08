"""Upload documents and inspect persisted metadata and chunks."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.document_schemas import ChunkResponse, DocumentResponse
from app.persistence import documents as repository
from app.persistence.database import get_session
from app.services.document_errors import DocumentError
from app.services.extraction import validate_file_metadata
from app.services.ingestion import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post("", status_code=201, summary="Upload and ingest documentation")
async def upload_document(
    request: Request,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
) -> DocumentResponse:
    settings = request.app.state.settings
    try:
        media_type = validate_file_metadata(file.filename, file.content_type)
        data = await file.read(settings.max_upload_bytes + 1)
        document, count = await ingest_document(
            session, file.filename, media_type, data, settings
        )
    except DocumentError as exc:
        codes = {"invalid": 400, "unsupported": 415, "too_large": 413}
        raise HTTPException(status_code=codes[exc.kind], detail=str(exc)) from exc
    finally:
        await file.close()
    return DocumentResponse.model_validate(document).model_copy(
        update={"chunk_count": count}
    )


@router.get("", summary="List uploaded documents")
async def get_documents(
    session: SessionDependency, limit: Limit = 20, offset: Offset = 0
) -> list[DocumentResponse]:
    rows = await repository.list_documents(session, limit, offset)
    return [
        DocumentResponse.model_validate(document).model_copy(
            update={"chunk_count": count}
        )
        for document, count in rows
    ]


@router.get("/{document_id}/chunks", summary="Inspect stored source chunks")
async def get_document_chunks(
    document_id: UUID,
    session: SessionDependency,
    limit: Limit = 20,
    offset: Offset = 0,
) -> list[ChunkResponse]:
    chunks = await repository.list_chunks(session, document_id, limit, offset)
    if chunks is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return [ChunkResponse.model_validate(chunk) for chunk in chunks]
