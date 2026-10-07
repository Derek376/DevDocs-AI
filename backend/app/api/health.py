"""Liveness endpoint: confirms the API can respond to requests."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.database import get_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/health", summary="Check API liveness")
async def health() -> HealthResponse:
    """Report API liveness without checking external dependencies."""
    return HealthResponse()


@router.get("/ready", summary="Check database connectivity")
async def ready(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealthResponse:
    """Check connectivity; migrations are applied separately, not by this route."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Database is unavailable. Check that PostgreSQL is running "
                "and credentials are correct."
            ),
        ) from exc
    return HealthResponse()
