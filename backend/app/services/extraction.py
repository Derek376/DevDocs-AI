"""Validate file metadata and extract plain text while retaining PDF pages."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath

from pypdf import PdfReader

from app.core.config import Settings
from app.services.document_errors import DocumentError

MEDIA_TYPES = {".txt": "text/plain", ".md": "text/markdown", ".pdf": "application/pdf"}
MAX_PAGE_STREAM_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class TextSection:
    text: str
    source_page: int | None = None


def validate_file_metadata(filename: str | None, content_type: str | None) -> str:
    """A filename is metadata only: it is never used as a filesystem path."""
    if (
        not filename
        or not filename.strip()
        or len(filename) > 255
        or any(char in filename for char in "/\\")
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)
    ):
        raise DocumentError(
            "Provide a filename of 1–255 characters without paths or controls."
        )
    suffix = PurePath(filename).suffix.lower()
    if suffix not in MEDIA_TYPES:
        raise DocumentError(
            "Supported file types are .txt, .md, and .pdf.", "unsupported"
        )
    media_type = MEDIA_TYPES[suffix]
    declared = (
        (content_type or "application/octet-stream").split(";", 1)[0].lower().strip()
    )
    allowed = {media_type, "application/octet-stream"}
    if suffix == ".md":
        allowed |= {"text/plain", "text/x-markdown"}
    if declared not in allowed:
        raise DocumentError(
            "The declared content type does not match the file extension.",
            "unsupported",
        )
    return media_type


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if any(ord(char) < 32 and char not in "\n\t" for char in text):
        raise DocumentError("Document text contains unsupported control characters.")
    # Preserve indentation in technical examples; discard only outer newlines.
    return text.strip("\n") if text.strip() else ""


def extract_sections(
    data: bytes, media_type: str, settings: Settings
) -> list[TextSection]:
    if not data:
        raise DocumentError("The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise DocumentError("File exceeds MAX_UPLOAD_BYTES.", "too_large")
    if media_type != "application/pdf":
        if data.startswith(b"%PDF-"):
            raise DocumentError(
                "PDF content must be uploaded with a .pdf extension.", "unsupported"
            )
        try:
            text = normalize_text(data.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise DocumentError(
                "Text and Markdown files must use UTF-8 encoding."
            ) from exc
        sections = [TextSection(text)] if text else []
    else:
        sections = extract_pdf(data, settings)

    if not sections:
        raise DocumentError(
            "No readable text was found. Empty or scanned PDFs require text content; "
            "OCR is not supported."
        )
    if sum(len(section.text) for section in sections) > settings.max_extracted_chars:
        raise DocumentError("Extracted text exceeds MAX_EXTRACTED_CHARS.", "too_large")
    return sections


def extract_pdf(data: bytes, settings: Settings) -> list[TextSection]:
    if not data.startswith(b"%PDF-"):
        raise DocumentError("The file does not have a valid PDF header.")
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise DocumentError(
                "Encrypted PDFs are not supported. Upload an unencrypted copy."
            )
        if len(reader.pages) > settings.max_pdf_pages:
            raise DocumentError("PDF exceeds MAX_PDF_PAGES.", "too_large")
        sections: list[TextSection] = []
        total_chars = 0
        for page_number, page in enumerate(reader.pages, start=1):
            contents = page.get_contents()
            if (
                contents is not None
                and len(contents.get_data()) > MAX_PAGE_STREAM_BYTES
            ):
                raise DocumentError(
                    "A PDF page is too complex to process.", "too_large"
                )
            text = normalize_text(page.extract_text() or "")
            total_chars += len(text)
            if total_chars > settings.max_extracted_chars:
                raise DocumentError(
                    "Extracted text exceeds MAX_EXTRACTED_CHARS.", "too_large"
                )
            if text:
                sections.append(TextSection(text, page_number))
        return sections
    except DocumentError:
        raise
    except Exception as exc:
        # PDF parser failures vary by malformed structure; never expose internals.
        raise DocumentError(
            "PDF could not be read. Upload a valid, text-based PDF."
        ) from exc
