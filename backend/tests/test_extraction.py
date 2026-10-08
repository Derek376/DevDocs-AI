from collections.abc import Callable

import pytest

from app.core.config import Settings
from app.services.document_errors import DocumentError
from app.services.extraction import (
    TextSection,
    extract_sections,
    validate_file_metadata,
)


def test_utf8_bom_newlines_and_code_indentation() -> None:
    assert extract_sections(
        b"\xef\xbb\xbf  print('hello')\r\nNext", "text/markdown", Settings()
    ) == [TextSection("  print('hello')\nNext")]


@pytest.mark.parametrize("data", [b"", b" \r\n\t", b"\xff\xfe", b"abc\x00def"])
def test_empty_binary_and_non_utf8_text_is_rejected(data: bytes) -> None:
    with pytest.raises(DocumentError):
        extract_sections(data, "text/plain", Settings())


@pytest.mark.parametrize(
    "filename", [None, "../guide.txt", "a\\guide.txt", "a\x00.txt", "x" * 256 + ".txt"]
)
def test_unsafe_filenames_are_rejected(filename: str | None) -> None:
    with pytest.raises(DocumentError):
        validate_file_metadata(filename, "text/plain")


def test_canonical_media_types_and_uppercase_extension() -> None:
    assert (
        validate_file_metadata("GUIDE.TXT", "text/plain; charset=utf-8") == "text/plain"
    )
    assert (
        validate_file_metadata("guide.md", "application/octet-stream")
        == "text/markdown"
    )


@pytest.mark.parametrize(
    "filename, media_type",
    [("file.exe", "application/octet-stream"), ("guide.txt", "image/png")],
)
def test_unsupported_type_and_mime_mismatch(filename: str, media_type: str) -> None:
    with pytest.raises(DocumentError) as error:
        validate_file_metadata(filename, media_type)
    assert error.value.kind == "unsupported"


def test_pdf_cannot_be_disguised_as_text() -> None:
    with pytest.raises(DocumentError, match=".pdf extension"):
        extract_sections(b"%PDF-1.7", "text/plain", Settings())


def test_pdf_retains_original_page_numbers_when_blank_pages_are_skipped(
    make_pdf: Callable,
) -> None:
    result = extract_sections(
        make_pdf(["Page one", None, "Page three"]), "application/pdf", Settings()
    )
    assert result == [TextSection("Page one", 1), TextSection("Page three", 3)]


@pytest.mark.parametrize("data", [b"not a pdf", b"%PDF-1.7\nmalformed"])
def test_corrupt_pdf_has_safe_error(data: bytes) -> None:
    with pytest.raises(DocumentError):
        extract_sections(data, "application/pdf", Settings())


def test_encrypted_and_blank_pdfs_are_rejected(make_pdf: Callable) -> None:
    with pytest.raises(DocumentError, match="Encrypted"):
        extract_sections(
            make_pdf(["Secret"], encrypted=True), "application/pdf", Settings()
        )
    with pytest.raises(DocumentError, match="OCR"):
        extract_sections(make_pdf([None]), "application/pdf", Settings())


def test_upload_and_extracted_text_limits() -> None:
    with pytest.raises(DocumentError) as error:
        extract_sections(b"12345", "text/plain", Settings(max_upload_bytes=4))
    assert error.value.kind == "too_large"
    with pytest.raises(DocumentError, match="MAX_EXTRACTED_CHARS"):
        extract_sections(b"12345", "text/plain", Settings(max_extracted_chars=4))


def test_pdf_page_text_and_stream_limits(
    make_pdf: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = make_pdf(["Page one", "Page two"])
    with pytest.raises(DocumentError, match="MAX_PDF_PAGES"):
        extract_sections(data, "application/pdf", Settings(max_pdf_pages=1))
    with pytest.raises(DocumentError, match="MAX_EXTRACTED_CHARS"):
        extract_sections(data, "application/pdf", Settings(max_extracted_chars=10))
    monkeypatch.setattr("app.services.extraction.MAX_PAGE_STREAM_BYTES", 10)
    with pytest.raises(DocumentError, match="too complex"):
        extract_sections(data, "application/pdf", Settings())
