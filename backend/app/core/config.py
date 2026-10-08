"""Load and validate backend configuration."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

# Resolve from this file so running from another directory does not change settings.
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Environment variables override dotenv values, which override defaults."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="DevDocs AI", min_length=1)
    app_env: Literal["development", "test", "production"] = "development"

    postgres_host: str = Field(default="127.0.0.1", min_length=1)
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = Field(default="devdocs", min_length=1)
    postgres_user: str = Field(default="devdocs", min_length=1)
    postgres_password: SecretStr | None = Field(default=None, min_length=1)

    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_extracted_chars: int = Field(default=1_000_000, ge=1)
    max_pdf_pages: int = Field(default=200, ge=1)
    chunk_size: int = Field(default=1000, ge=100, le=10_000)
    chunk_overlap: int = Field(default=150, ge=0)

    ollama_base_url: str = "http://127.0.0.1:11434"
    embedding_model: str = Field(default="embeddinggemma", min_length=1, max_length=200)
    embedding_dimensions: int = Field(default=768, ge=1, le=16000)
    embedding_batch_size: int = Field(default=32, ge=1, le=128)
    embedding_timeout_seconds: float = Field(default=120, gt=0, le=600)
    llm_model: str = Field(default="llama3.2:1b", min_length=1, max_length=200)
    llm_timeout_seconds: float = Field(default=120, gt=0, le=600)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE.")
        return self

    @property
    def database_url(self) -> URL:
        """Build a URL without manual interpolation or password escaping."""
        if self.postgres_password is None:
            raise ValueError("Set POSTGRES_PASSWORD to configure the database.")
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
