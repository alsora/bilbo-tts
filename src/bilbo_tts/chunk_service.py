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
    """Render chunk sizes, pause metadata, and source-to-chunk mapping."""

    lengths = sorted(len(chunk.spoken_text) for chunk in manifest.chunks)
    mapping: dict[str, list[str]] = {}
    for chunk in manifest.chunks:
        mapping.setdefault(chunk.paragraph_id, []).append(chunk.chunk_id)
    lines = [
        f"# Chunking report: {manifest.book_id}",
        "",
        f"- Character limit: {max_characters}",
        f"- Chunks: {len(manifest.chunks)}",
        f"- Minimum characters: {min(lengths, default=0)}",
        f"- Median characters: {_percentile(lengths, 50)}",
        f"- 95th percentile characters: {_percentile(lengths, 95)}",
        f"- Maximum characters: {max(lengths, default=0)}",
        "",
        "## Limit outliers",
        "",
    ]
    lines.append("- None.")
    lines.extend(["", "## Source-to-chunk mapping", ""])
    if mapping:
        lines.extend(
            f"- `{block_id}` → {', '.join(f'`{chunk_id}`' for chunk_id in chunk_ids)}"
            for block_id, chunk_ids in mapping.items()
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Chunks", ""])
    for chunk in manifest.chunks:
        lines.extend(
            [
                f"### `{chunk.chunk_id}`",
                "",
                f"- Sequence: {chunk.sequence}",
                f"- Chapter: `{chunk.chapter_id}`",
                f"- Source block: `{chunk.paragraph_id}`",
                f"- Sentence: `{chunk.sentence_id}`",
                f"- Characters: {len(chunk.spoken_text)}",
                f"- Break before: `{chunk.pause.break_before.value}` "
                f"({chunk.pause.duration_ms} ms)",
                "",
                chunk.spoken_text,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    index = ((len(values) - 1) * percentile + 99) // 100
    return values[index]
