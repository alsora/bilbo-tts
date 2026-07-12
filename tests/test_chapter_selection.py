from __future__ import annotations

import pytest

from bilbo_tts.chapter_selection import ChapterSelectionError, select_chapter_ids
from bilbo_tts.models import BreakKind, ChunkManifest, ChunkRecord, PauseMetadata


def _manifest() -> ChunkManifest:
    return ChunkManifest(
        book_id="book",
        normalized_document_sha256="a" * 64,
        chunks=tuple(
            ChunkRecord.create(
                chunk_id=f"chunk-{index}",
                chapter_id=f"chapter-{index}",
                paragraph_id=f"paragraph-{index}",
                sentence_id=f"sentence-{index}",
                sequence=index - 1,
                display_text=f"Capitolo {index}.",
                spoken_text=f"Capitolo {index}.",
                pause=PauseMetadata(
                    break_before=BreakKind.CHAPTER,
                    duration_ms=100,
                ),
            )
            for index in range(1, 8)
        ),
    )


def test_accepts_five_contiguous_chapters_in_manifest_order() -> None:
    chapters = tuple(f"chapter-{index}" for index in range(2, 7))

    assert select_chapter_ids(_manifest(), chapters) == chapters


@pytest.mark.parametrize(
    ("chapters", "match"),
    [
        ((), "must not be empty"),
        (("chapter-2", ""), "empty identifier"),
        (("chapter-2", "chapter-2"), "duplicates"),
        (("missing",), "does not exist"),
        (("chapter-3", "chapter-2"), "manifest order"),
        (("chapter-2", "chapter-4"), "contiguous"),
    ],
)
def test_rejects_invalid_chapter_scopes(
    chapters: tuple[str, ...],
    match: str,
) -> None:
    with pytest.raises(ChapterSelectionError, match=match):
        select_chapter_ids(_manifest(), chapters)
