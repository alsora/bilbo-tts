"""Chunk-stage orchestration, artifacts, summaries, and reports."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from bilbo_tts.chunking import build_chunk_manifest
from bilbo_tts.ingest.service import DOCUMENT_PATH
from bilbo_tts.models import (
    BookDocument,
    ChunkManifest,
    ChunkRecord,
    ContractModel,
    NonEmptyText,
    NormalizedDocument,
    Sha256,
)
from bilbo_tts.normalization.service import NORMALIZED_PATH
from bilbo_tts.stages import load_stage_context

CHUNK_MANIFEST_PATH = "manifests/chunk-manifest.json"
CHUNK_REPORT_PATH = "reports/chunking.md"


class ChunkSummary(ContractModel):
    """Machine-readable result emitted by the chunk stage."""

    schema_version: Literal["chunk-summary/v1"] = "chunk-summary/v1"
    status: Literal["completed"] = "completed"
    book_id: NonEmptyText
    normalized_sha256: Sha256
    chunk_manifest_path: NonEmptyText
    chunk_manifest_sha256: Sha256
    report_path: NonEmptyText
    report_sha256: Sha256
    chunk_count: int = Field(ge=0)
    max_characters: int = Field(gt=0)
    largest_chunk_characters: int = Field(ge=0)


def chunk_book(config_path: Path, project_root: Path) -> ChunkSummary:
    """Split one normalized document into stable synthesis chunks."""

    context = load_stage_context(config_path, project_root)
    store = context.workspace.artifacts
    document = store.read(DOCUMENT_PATH, BookDocument)
    document_reference = store.reference(DOCUMENT_PATH)
    normalized = store.read(NORMALIZED_PATH, NormalizedDocument)
    normalized_reference = store.reference(NORMALIZED_PATH)
    manifest = build_chunk_manifest(
        document,
        normalized,
        book_document_sha256=document_reference.sha256,
        normalized_document_sha256=normalized_reference.sha256,
        max_characters=context.config.chunking.max_characters,
        pauses=context.config.assembly.pauses,
        pack_sentences=context.config.chunking.pack_sentences,
    )
    manifest_reference = store.write(
        CHUNK_MANIFEST_PATH,
        manifest,
        dependencies=(document_reference, normalized_reference),
    )
    report = render_chunk_report(manifest, context.config.chunking.max_characters)
    report_reference = store.write_bytes(CHUNK_REPORT_PATH, report.encode("utf-8"))
    lengths = [len(chunk.spoken_text) for chunk in manifest.chunks]
    return ChunkSummary(
        book_id=manifest.book_id,
        normalized_sha256=normalized_reference.sha256,
        chunk_manifest_path=manifest_reference.path,
        chunk_manifest_sha256=manifest_reference.sha256,
        report_path=report_reference.path,
        report_sha256=report_reference.sha256,
        chunk_count=len(manifest.chunks),
        max_characters=context.config.chunking.max_characters,
        largest_chunk_characters=max(lengths, default=0),
    )


def render_chunk_report(manifest: ChunkManifest, max_characters: int) -> str:
    """Render chapter metrics, forced sentence splits, and invariant failures."""

    lengths = sorted(len(chunk.spoken_text) for chunk in manifest.chunks)
    chunks_by_block: dict[str, list[ChunkRecord]] = {}
    chunks_by_chapter: dict[str, list[ChunkRecord]] = {}
    for chunk in manifest.chunks:
        chunks_by_block.setdefault(chunk.paragraph_id, []).append(chunk)
        chunks_by_chapter.setdefault(chunk.chapter_id, []).append(chunk)
    forced_splits_by_chapter = {
        chapter_id: _forced_sentence_splits(chunks)
        for chapter_id, chunks in chunks_by_chapter.items()
    }
    forced_split_count = sum(
        _forced_split_count(groups) for groups in forced_splits_by_chapter.values()
    )
    chunks_at_limit = sum(len(chunk.spoken_text) == max_characters for chunk in manifest.chunks)
    anomalies = _chunk_anomalies(manifest, max_characters)
    lines = [
        f"# Chunking report: {manifest.book_id}",
        "",
        f"- Character limit: {max_characters}",
        f"- Chapters: {len(chunks_by_chapter)}",
        f"- Chunks: {len(manifest.chunks)}",
        f"- Source blocks: {len(chunks_by_block)}",
        f"- Forced intra-sentence splits: {forced_split_count}",
        f"- Chunks exactly at limit: {chunks_at_limit}",
        f"- Minimum characters: {min(lengths, default=0)}",
        f"- Median characters: {_percentile(lengths, 50)}",
        f"- 95th percentile characters: {_percentile(lengths, 95)}",
        f"- Maximum characters: {max(lengths, default=0)}",
        "",
        "## Chapter summary",
        "",
    ]
    for chapter_id, chunks in chunks_by_chapter.items():
        chapter_lengths = [len(chunk.spoken_text) for chunk in chunks]
        chapter_forced_split_count = _forced_split_count(forced_splits_by_chapter[chapter_id])
        lines.append(
            f"- `{chapter_id}`: "
            f"{_count_label(len({chunk.paragraph_id for chunk in chunks}), 'block')}; "
            f"{_count_label(len({chunk.sentence_id for chunk in chunks}), 'sentence')}; "
            f"{_count_label(len(chunks), 'chunk')}; "
            f"{_count_label(chapter_forced_split_count, 'forced split')}; "
            f"maximum {max(chapter_lengths)} characters"
        )
    if not chunks_by_chapter:
        lines.append("- None.")

    lines.extend(["", "## Forced intra-sentence splits", ""])
    if not forced_split_count:
        lines.extend(["- None.", ""])
    for chapter_id, sentence_groups in forced_splits_by_chapter.items():
        if not sentence_groups:
            continue
        lines.extend([f"### `{chapter_id}`", ""])
        for chunks in sentence_groups:
            lengths_label = " + ".join(str(len(chunk.spoken_text)) for chunk in chunks)
            for boundary, (left, right) in enumerate(
                zip(chunks, chunks[1:], strict=False),
                start=1,
            ):
                lines.append(
                    f"- `{chunks[0].sentence_id}` boundary {boundary} "
                    f"(`{chunks[0].paragraph_id}`; {lengths_label} characters; "
                    f"{right.pause.break_before.value}, {right.pause.duration_ms} ms)"
                )
                lines.extend(
                    [
                        "",
                        f"  {_split_context(left.spoken_text, right.spoken_text)}",
                        "",
                    ]
                )

    lines.extend(["## Ordering, limit, and pause anomalies", ""])
    if anomalies:
        lines.extend(f"- {anomaly}" for anomaly in anomalies)
    else:
        lines.append("- None.")
    return "\n".join(lines).rstrip() + "\n"


def render_chunk_chapter_report(manifest: ChunkManifest, chapter_id: str) -> str:
    """Render every chunk and pause decision in one selected chapter."""

    chapter_chunks = [chunk for chunk in manifest.chunks if chunk.chapter_id == chapter_id]
    chunks_by_block: dict[str, list[ChunkRecord]] = {}
    for chunk in chapter_chunks:
        chunks_by_block.setdefault(chunk.paragraph_id, []).append(chunk)
    lengths = [len(chunk.spoken_text) for chunk in chapter_chunks]
    lines = [
        f"# Chunking chapter review: {chapter_id}",
        "",
        f"- Book: `{manifest.book_id}`",
        f"- Source blocks: {len(chunks_by_block)}",
        f"- Chunks: {len(chapter_chunks)}",
        f"- Maximum characters: {max(lengths, default=0)}",
        "",
    ]
    for block_id, chunks in chunks_by_block.items():
        lines.extend(
            [
                f"## `{block_id}` — {len(chunks)} chunk{'s' if len(chunks) != 1 else ''}",
                "",
            ]
        )
        for chunk in chunks:
            break_kind = chunk.pause.break_before.value
            if break_kind == "none":
                break_kind = "none (continuation)"
            lines.extend(
                [
                    f"### `{chunk.chunk_id}`",
                    "",
                    f"- Characters: {len(chunk.spoken_text)}",
                    f"- Break before: `{break_kind}` ({chunk.pause.duration_ms} ms)",
                    "",
                    chunk.spoken_text,
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _forced_sentence_splits(chunks: list[ChunkRecord]) -> list[list[ChunkRecord]]:
    chunks_by_sentence: dict[str, list[ChunkRecord]] = {}
    for chunk in chunks:
        chunks_by_sentence.setdefault(chunk.sentence_id, []).append(chunk)
    return [
        sentence_chunks
        for sentence_chunks in chunks_by_sentence.values()
        if len(sentence_chunks) > 1
    ]


def _forced_split_count(sentence_groups: list[list[ChunkRecord]]) -> int:
    return sum(len(chunks) - 1 for chunks in sentence_groups)


def _chunk_anomalies(manifest: ChunkManifest, max_characters: int) -> list[str]:
    anomalies: list[str] = []
    previous: ChunkRecord | None = None
    for expected_sequence, chunk in enumerate(manifest.chunks):
        if chunk.sequence != expected_sequence:
            anomalies.append(
                f"`{chunk.chunk_id}` has sequence {chunk.sequence}, expected {expected_sequence}"
            )
        if len(chunk.spoken_text) > max_characters:
            anomalies.append(
                f"`{chunk.chunk_id}` has {len(chunk.spoken_text)} characters, "
                f"exceeding {max_characters}"
            )
        expected_break = "chapter"
        if previous is not None and previous.chapter_id == chunk.chapter_id:
            if previous.paragraph_id != chunk.paragraph_id:
                expected_break = "paragraph"
            elif previous.sentence_id != chunk.sentence_id:
                expected_break = "sentence"
            else:
                expected_break = "none"
        if chunk.pause.break_before.value != expected_break:
            anomalies.append(
                f"`{chunk.chunk_id}` uses `{chunk.pause.break_before.value}` break, "
                f"expected `{expected_break}`"
            )
        previous = chunk
    return anomalies


def _split_context(left: str, right: str, context_characters: int = 80) -> str:
    left_context = left[-context_characters:]
    right_context = right[:context_characters]
    left_prefix = "…" if len(left) > context_characters else ""
    right_suffix = "…" if len(right) > context_characters else ""
    return f"{left_prefix}{left_context} ⟦SPLIT⟧ {right_context}{right_suffix}"


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    index = ((len(values) - 1) * percentile + 99) // 100
    return values[index]


def _count_label(count: int, noun: str) -> str:
    return f"{count} {noun}{'s' if count != 1 else ''}"
