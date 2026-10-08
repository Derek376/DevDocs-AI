"""Keep tests independent of developer configuration."""

from collections.abc import Callable, Iterator
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.config import Settings
from app.main import create_app


@pytest.fixture(autouse=True)
def clean_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(app_env="test")
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def make_pdf() -> Callable[..., bytes]:
    """Build small real PDFs without needing an external fixture generator."""

    def build(pages: list[str | None], encrypted: bool = False) -> bytes:
        writer = PdfWriter()
        for text in pages:
            page = writer.add_blank_page(width=612, height=792)
            if text is not None:
                font = DictionaryObject(
                    {
                        NameObject("/Type"): NameObject("/Font"),
                        NameObject("/Subtype"): NameObject("/Type1"),
                        NameObject("/BaseFont"): NameObject("/Helvetica"),
                    }
                )
                page[NameObject("/Resources")] = DictionaryObject(
                    {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
                )
                escaped = (
                    text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                )
                contents = DecodedStreamObject()
                contents.set_data(
                    f"BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET".encode("ascii")
                )
                page[NameObject("/Contents")] = contents
        if encrypted:
            writer.encrypt("fixture-password")
        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    return build
