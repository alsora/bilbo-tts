"""Shared ordered chapter-scope validation."""

from __future__ import annotations

from bilbo_tts.models import ChunkManifest


class ChapterSelectionError(ValueError):
    """A requested chapter scope is not a valid manifest slice."""


def select_chapter_ids(
    manifest: ChunkManifest,
    chapters: tuple[str, ...] | None,
) -> tuple[str, ...]:
    """Return a non-empty contiguous chapter scope in manifest order."""

    available = tuple(dict.fromkeys(chunk.chapter_id for chunk in manifest.chunks))
    if chapters is None:
        return available
    if not chapters:
        raise ChapterSelectionError("chapter selection must not be empty")
    if any(not chapter.strip() for chapter in chapters):
        raise ChapterSelectionError("chapter selection must not contain an empty identifier")
    if len(chapters) != len(set(chapters)):
        raise ChapterSelectionError("chapter selection must not contain duplicates")

    positions = {chapter: index for index, chapter in enumerate(available)}
    unknown = tuple(chapter for chapter in chapters if chapter not in positions)
    if unknown:
        raise ChapterSelectionError(f"chapter {unknown[0]!r} does not exist in the chunk manifest")
    indexes = tuple(positions[chapter] for chapter in chapters)
    if indexes != tuple(sorted(indexes)):
        raise ChapterSelectionError("chapter selection must follow manifest order")
    if indexes != tuple(range(indexes[0], indexes[-1] + 1)):
        raise ChapterSelectionError("chapter selection must be contiguous in manifest order")
    return chapters
