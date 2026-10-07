from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import ENV_FILE, Settings
from app.main import create_app


def test_default_settings() -> None:
    settings = Settings()

    assert settings.app_name == "DevDocs AI"
    assert settings.app_env == "development"


def test_environment_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("APP_NAME=From file\nAPP_ENV=production\n", encoding="utf-8")
    monkeypatch.setenv("APP_NAME", "From environment")

    settings = Settings(_env_file=env_file)

    assert settings.app_name == "From environment"
    assert settings.app_env == "production"
    assert Settings(app_name="Explicit", _env_file=env_file).app_name == "Explicit"


@pytest.mark.parametrize("value", ["staging", "", "invalid"])
def test_invalid_environment_prevents_app_creation(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", value)

    with pytest.raises(ValidationError, match="app_env"):
        create_app()


def test_factory_uses_supplied_configuration() -> None:
    settings = Settings(app_name="Test API", app_env="test")

    app = create_app(settings)

    assert app.title == "Test API"
    assert app.state.settings is settings


def test_dotenv_path_does_not_depend_on_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert ENV_FILE == Path(__file__).resolve().parents[2] / ".env"
