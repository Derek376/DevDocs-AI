"""Deterministic character windows, independently applied to each PDF page."""

from app.services.extraction import TextSection


def chunk_sections(
    sections: list[TextSection], chunk_size: int, overlap: int
) -> list[TextSection]:
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("Require positive chunk_size and 0 <= overlap < chunk_size.")
    chunks: list[TextSection] = []
    for section in sections:
        start = 0
        while start < len(section.text):
            end = min(start + chunk_size, len(section.text))
            text = section.text[start:end]
            if text.strip():
                chunks.append(TextSection(text, section.source_page))
            if end == len(section.text):
                break
            start = end - overlap
    return chunks
