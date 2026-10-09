"""Application factory used by the server and tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.embeddings import EmbeddingError
from app.ai.llm import LLMError
from app.ai.openai import OpenAIEmbeddingProvider, OpenAILLMProvider
from app.api.agent import router as agent_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.questions import router as questions_router
from app.api.search import router as search_router
from app.core.config import Settings
from app.core.logging import configure_logging, logger
from app.core.middleware import RequestLoggingMiddleware
from app.persistence.database import create_database_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application after validating configuration."""
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        engine = None
        client = httpx.AsyncClient(trust_env=False)
        app.state.embedding_provider = OpenAIEmbeddingProvider(settings, client)
        app.state.llm_provider = OpenAILLMProvider(settings, client)
        app.state.session_factory = None
        if settings.postgres_password is not None:
            engine = create_database_engine(settings)
            app.state.session_factory = async_sessionmaker(
                engine, expire_on_commit=False
            )
        try:
            logger.info("application_started")
            yield
        finally:
            await client.aclose()
            if engine is not None:
                await engine.dispose()
            logger.info("application_stopped")

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(search_router)
    app.include_router(questions_router)
    app.include_router(agent_router)

    @app.exception_handler(LLMError)
    async def llm_error(request: Request, exc: LLMError) -> JSONResponse:
        request.state.error_type = type(exc).__name__
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(EmbeddingError)
    async def embedding_error(request: Request, exc: EmbeddingError) -> JSONResponse:
        request.state.error_type = type(exc).__name__
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        request.state.error_type = type(exc).__name__
        return JSONResponse(
            status_code=503,
            content={"detail": "Database operation failed. Please try again later."},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Keep useful field locations/messages without echoing submitted input.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: error[key] for key in ("loc", "msg", "type")}
                    for error in exc.errors()
                ]
            },
        )

    return app
