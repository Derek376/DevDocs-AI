"""Liveness endpoint: confirms the API can respond to requests."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/health", summary="Check API liveness")
async def health() -> HealthResponse:
    """Report API liveness without checking external dependencies."""
    return HealthResponse()
