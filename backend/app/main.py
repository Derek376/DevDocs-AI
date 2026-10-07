"""Application factory used by the server and tests."""

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application after validating configuration."""
    if settings is None:
        settings = Settings()

    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings
    app.include_router(health_router)
    return app
