import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_missing_password_has_clear_configuration_error() -> None:
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        _ = Settings().database_url


def test_database_url_preserves_special_characters_and_hides_password() -> None:
    password = "test:@/ password"
    settings = Settings(postgres_user="test-user", postgres_password=password)

    assert settings.database_url.password == password
    assert settings.database_url.drivername == "postgresql+psycopg"
    assert password not in repr(settings)
    assert password not in str(settings.database_url)


@pytest.mark.parametrize("port", [0, 65536])
def test_invalid_database_port_is_rejected(port: int) -> None:
    with pytest.raises(ValidationError, match="postgres_port"):
        Settings(postgres_port=port)


def test_empty_database_password_is_rejected() -> None:
    with pytest.raises(ValidationError, match="postgres_password"):
        Settings(postgres_password="")
