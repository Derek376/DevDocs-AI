"""Application factory used by the server and tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.core.config import Settings
from app.persistence.database import create_database_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application after validating configuration."""
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = None
        app.state.session_factory = None
        if settings.postgres_password is not None:
            engine = create_database_engine(settings)
            app.state.session_factory = async_sessionmaker(
                engine, expire_on_commit=False
            )
        try:
            yield
        finally:
            if engine is not None:
                await engine.dispose()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health_router)
    app.include_router(documents_router)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Database operation failed. Please try again later."},
        )

    return app
