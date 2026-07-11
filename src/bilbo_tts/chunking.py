"""Paragraph-first, sentence-aware deterministic chunking."""

from __future__ import annotations

import re

from bilbo_tts.config import PauseConfig
from bilbo_tts.models import (
    BookDocument,
    BreakKind,
    ChunkManifest,
    ChunkRecord,
    NormalizedDocument,
    PauseMetadata,
)

_PROTECTED_PERIOD = "\ue000"
_ABBREVIATIONS = (
    "dott.",
    "dott.ssa.",
    "prof.",
    "prof.ssa.",
    "sig.",
    "sig.ra.",
    "sig.na.",
    "ecc.",
    "es.",
    "art.",
    "n.",
    "cap.",
    "pag.",
    "sec.",
    "ca.",
    "vs.",
)


class ChunkingError(ValueError):
    """Normalized text cannot be split without violating chunk contracts."""


def split_sentences(text: str) -> tuple[str, ...]:
    """Split Italian prose while protecting common abbreviations and initials."""

    protected = text
    for abbreviation in sorted(_ABBREVIATIONS, key=len, reverse=True):
        protected = re.sub(
            re.escape(abbreviation),
            abbreviation.replace(".", _PROTECTED_PERIOD),
            protected,
            flags=re.IGNORECASE,
        )
    protected = re.sub(
        r"(?<!\w)([A-ZÀ-ÖØ-Ý])\.(?=\s+[A-ZÀ-ÖØ-Ý])",
        rf"\1{_PROTECTED_PERIOD}",
        protected,
    )
    pieces = re.split(r"(?<=[.!?])\s+", protected.strip())
    return tuple(piece.replace(_PROTECTED_PERIOD, ".").strip() for piece in pieces if piece.strip())


def split_to_limit(text: str, max_characters: int) -> tuple[str, ...]:
    """Split over-limit text at punctuation, then whitespace."""

    if max_characters <= 0:
        raise ChunkingError("max_characters must be positive")
    remaining = text.strip()
    parts: list[str] = []
    while len(remaining) > max_characters:
        window = remaining[: max_characters + 1]
        split_at = _strong_split(window, max_characters)
        if split_at is None:
            split_at = window.rfind(" ", 0, max_characters + 1)
        if split_at is None or split_at <= 0:
            preview = remaining[: min(len(remaining), 40)]
            raise ChunkingError(
                f"cannot split text within {max_characters} characters near {preview!r}"
            )
        part = remaining[:split_at].strip()
        remaining = remaining[split_at:].strip()
        if not part or not remaining:
            raise ChunkingError("chunk splitting produced an empty continuation")
        parts.append(part)
    if remaining:
        parts.append(remaining)
    return tuple(parts)


def build_chunk_manifest(
    document: BookDocument,
    normalized: NormalizedDocument,
    *,
    book_document_sha256: str,
    normalized_document_sha256: str,
    max_characters: int,
    pauses: PauseConfig,
) -> ChunkManifest:
    """Map normalized blocks to stable, ordered synthesis chunks."""

    if document.book_id != normalized.book_id:
        raise ChunkingError(
            f"normalized document belongs to {normalized.book_id!r}, expected {document.book_id!r}"
        )
    if normalized.book_document_sha256 != book_document_sha256:
        raise ChunkingError(
            "normalized document does not reference the current canonical book document"
        )
    normalized_by_id = {block.block_id: block for block in normalized.blocks}
    source_ids = [block.block_id for chapter in document.chapters for block in chapter.blocks]
    if set(normalized_by_id) != set(source_ids):
        missing = sorted(set(source_ids) - set(normalized_by_id))
        extra = sorted(set(normalized_by_id) - set(source_ids))
        raise ChunkingError(
            f"normalized block IDs do not match source; missing={missing}, extra={extra}"
        )

    chunks: list[ChunkRecord] = []
    for chapter in document.chapters:
        for block_index, source_block in enumerate(chapter.blocks):
            block = normalized_by_id[source_block.block_id]
            spoken_sentences = split_sentences(block.spoken_text)
            display_sentences = split_sentences(block.display_text)
            if not spoken_sentences:
                raise ChunkingError(f"block {block.block_id} contains no spoken sentences")
            displays_align = len(display_sentences) == len(spoken_sentences)
            for sentence_index, sentence in enumerate(spoken_sentences):
                parts = split_to_limit(sentence, max_characters)
                sentence_id = f"{block.block_id}.s{sentence_index:04d}"
                display = (
                    display_sentences[sentence_index] if displays_align else block.display_text
                )
                for part_index, part in enumerate(parts):
                    pause = _pause_for(
                        block_index=block_index,
                        sentence_index=sentence_index,
                        part_index=part_index,
                        pauses=pauses,
                    )
                    chunk_id = f"{sentence_id}.p{part_index:04d}"
                    chunks.append(
                        ChunkRecord.create(
                            chunk_id=chunk_id,
                            chapter_id=chapter.chapter_id,
                            paragraph_id=block.block_id,
                            sentence_id=sentence_id,
                            sequence=len(chunks),
                            display_text=display,
                            spoken_text=part,
                            pause=pause,
                        )
                    )
    return ChunkManifest(
        book_id=document.book_id,
        normalized_document_sha256=normalized_document_sha256,
        chunks=tuple(chunks),
    )


def _strong_split(window: str, limit: int) -> int | None:
    positions = [
        match.end()
        for match in re.finditer(r"[;,:](?:\s+|$)", window[: limit + 1])
        if match.end() <= limit
    ]
    return positions[-1] if positions else None


def _pause_for(
    *,
    block_index: int,
    sentence_index: int,
    part_index: int,
    pauses: PauseConfig,
) -> PauseMetadata:
    if part_index:
        return PauseMetadata(break_before=BreakKind.NONE, duration_ms=0)
    if block_index == 0 and sentence_index == 0:
        return PauseMetadata(break_before=BreakKind.CHAPTER, duration_ms=pauses.chapter_ms)
    if sentence_index == 0:
        return PauseMetadata(break_before=BreakKind.PARAGRAPH, duration_ms=pauses.paragraph_ms)
    return PauseMetadata(break_before=BreakKind.SENTENCE, duration_ms=pauses.sentence_ms)
