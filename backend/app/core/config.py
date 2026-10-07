"""Load and validate backend configuration."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
