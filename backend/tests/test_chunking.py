import pytest

from app.services.chunking import chunk_sections
from app.services.extraction import TextSection


def test_overlap_preserves_boundary_context_and_last_character() -> None:
    chunks = chunk_sections([TextSection("abcdefghijklm")], chunk_size=6, overlap=2)

    assert [chunk.text for chunk in chunks] == ["abcdef", "efghij", "ijklm"]
    assert all(len(chunk.text) <= 6 for chunk in chunks)
    assert (
        chunks[0].text + "".join(chunk.text[2:] for chunk in chunks[1:])
        == "abcdefghijklm"
    )


def test_exact_size_does_not_emit_overlap_only_tail() -> None:
    assert chunk_sections([TextSection("abcdef")], 6, 2) == [TextSection("abcdef")]


def test_page_boundaries_and_indentation_are_preserved() -> None:
    chunks = chunk_sections([TextSection("  code", 1), TextSection("next", 3)], 20, 5)

    assert chunks == [TextSection("  code", 1), TextSection("next", 3)]


def test_zero_overlap_and_whitespace_only_windows() -> None:
    assert chunk_sections([TextSection("abc   def")], 3, 0) == [
        TextSection("abc"),
        TextSection("def"),
    ]


@pytest.mark.parametrize("size, overlap", [(0, 0), (5, -1), (5, 5), (5, 6)])
def test_invalid_chunk_settings_cannot_loop_forever(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_sections([TextSection("text")], size, overlap)
