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


def split_sentences(text: str, *, split_at_colons: bool = False) -> tuple[str, ...]:
    """Split Italian prose while protecting common abbreviations and initials.

    With ``split_at_colons`` enabled, a colon followed by whitespace also ends
    a sentence so the next clause receives an explicit assembly pause.
    """

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
    boundary = r"(?<=[.!?:])\s+" if split_at_colons else r"(?<=[.!?])\s+"
    pieces = re.split(boundary, protected.strip())
    return tuple(piece.replace(_PROTECTED_PERIOD, ".").strip() for piece in pieces if piece.strip())


def split_to_limit(text: str, max_characters: int) -> tuple[str, ...]:
    """Split over-limit text at punctuation, then whitespace."""

    if max_characters <= 0:
        raise ChunkingError("max_characters must be positive")
    remaining = text.strip()
    parts: list[str] = []
    while len(remaining) > max_characters:
        window = remaining[: max_characters + 1]
        split_at = _strong_split(remaining, max_characters)
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
    pack_sentences: bool = False,
    split_at_colons: bool = False,
) -> ChunkManifest:
    """Map normalized blocks to stable, ordered synthesis chunks.

    With ``pack_sentences`` enabled, adjacent whole sentences of one block are
    greedily merged up to ``max_characters`` so fewer chunks amortize the
    per-chunk synthesis overhead; merged chunks keep the pause of their first
    sentence and intra-chunk sentence pauses come from the model's prosody.
    With ``split_at_colons`` enabled, colons also end sentences so the next
    clause receives an explicit assembly sentence pause.
    """

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
            spoken_sentences = split_sentences(block.spoken_text, split_at_colons=split_at_colons)
            display_sentences = split_sentences(block.display_text, split_at_colons=split_at_colons)
            if not spoken_sentences:
                raise ChunkingError(f"block {block.block_id} contains no spoken sentences")
            displays_align = len(display_sentences) == len(spoken_sentences)
            groups = (
                _pack_sentences(spoken_sentences, max_characters)
                if pack_sentences
                else tuple((index, index) for index in range(len(spoken_sentences)))
            )
            for start, end in groups:
                spoken = " ".join(spoken_sentences[start : end + 1])
                parts = split_to_limit(spoken, max_characters)
                sentence_id = (
                    f"{block.block_id}.s{start:04d}"
                    if start == end
                    else f"{block.block_id}.s{start:04d}-s{end:04d}"
                )
                display = (
                    " ".join(display_sentences[start : end + 1])
                    if displays_align
                    else block.display_text
                )
                for part_index, part in enumerate(parts):
                    pause = _pause_for(
                        block_index=block_index,
                        sentence_index=start,
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


def _pack_sentences(
    sentences: tuple[str, ...],
    max_characters: int,
) -> tuple[tuple[int, int], ...]:
    """Greedily group adjacent whole sentences up to the character limit."""

    groups: list[tuple[int, int]] = []
    start = 0
    length = len(sentences[0])
    for index in range(1, len(sentences)):
        addition = 1 + len(sentences[index])
        if length + addition <= max_characters:
            length += addition
        else:
            groups.append((start, index - 1))
            start = index
            length = len(sentences[index])
    groups.append((start, len(sentences) - 1))
    return tuple(groups)


def _strong_split(text: str, limit: int) -> int | None:
    candidates = [
        (match.end(), 2 if match.group(0)[0] in ";:" else 1)
        for match in re.finditer(r"[;,:](?:\s+|$)", text[: limit + 1])
        if match.end() <= limit
    ]
    if not candidates:
        return None

    minimum_part = max(1, limit // 4)
    two_part_candidates = [
        candidate
        for candidate in candidates
        if candidate[0] >= minimum_part and minimum_part <= len(text) - candidate[0] <= limit
    ]
    if two_part_candidates:
        strongest = max(strength for _, strength in two_part_candidates)
        strongest_candidates = [
            candidate for candidate in two_part_candidates if candidate[1] == strongest
        ]
        midpoint = len(text) / 2
        return min(
            strongest_candidates,
            key=lambda candidate: abs(candidate[0] - midpoint),
        )[0]
    return candidates[-1][0]


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
