"""Async connection pooling and request-scoped sessions."""

from collections.abc import AsyncIterator

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one session; callers explicitly commit successful writes."""
    session_factory = request.app.state.session_factory
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Database is not configured. Set POSTGRES_PASSWORD "
                "in the backend environment."
            ),
        )

    # Closing the session rolls back uncommitted work, including on exceptions.
    async with session_factory() as session:
        yield session
