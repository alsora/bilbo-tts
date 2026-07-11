"""Focused human-review reports derived from validated text artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from bilbo_tts.chunk_service import CHUNK_MANIFEST_PATH, render_chunk_chapter_report
from bilbo_tts.ingest.service import (
    DOCUMENT_PATH,
    render_extraction_chapter_report,
)
from bilbo_tts.models import (
    BookDocument,
    ChapterDocument,
    ChunkManifest,
    ContractModel,
    NonEmptyText,
    Sha256,
)
from bilbo_tts.stages import load_stage_context

REVIEW_REPORT_DIR = "reports/review"


class ReviewError(ValueError):
    """A focused text review cannot be generated from the stored artifacts."""


class ExtractionReviewSummary(ContractModel):
    """Machine-readable result emitted by the review-extraction command."""

    schema_version: Literal["extraction-review-summary/v1"] = "extraction-review-summary/v1"
    status: Literal["completed"] = "completed"
    book_id: NonEmptyText
    chapter_id: NonEmptyText
    report_path: NonEmptyText
    report_sha256: Sha256
    block_count: int = Field(ge=0)


class ChunkReviewSummary(ContractModel):
    """Machine-readable result emitted by the review-chunking command."""

    schema_version: Literal["chunk-review-summary/v1"] = "chunk-review-summary/v1"
    status: Literal["completed"] = "completed"
    book_id: NonEmptyText
    chapter_id: NonEmptyText
    report_path: NonEmptyText
    report_sha256: Sha256
    block_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)


def write_extraction_review(
    config_path: Path,
    project_root: Path,
    chapter_id: str,
) -> ExtractionReviewSummary:
    """Write a complete extraction report for one chapter."""

    context = load_stage_context(config_path, project_root)
    store = context.workspace.artifacts
    document = store.read(DOCUMENT_PATH, BookDocument)
    if document.book_id != context.config.book_id:
        raise ReviewError("stored book document belongs to a different book")
    chapter = _resolve_chapter(document, chapter_id)
    report_path = f"{REVIEW_REPORT_DIR}/{chapter.chapter_id}-extraction.md"
    report_reference = store.write_bytes(
        report_path,
        render_extraction_chapter_report(document, chapter).encode("utf-8"),
    )
    return ExtractionReviewSummary(
        book_id=context.config.book_id,
        chapter_id=chapter.chapter_id,
        report_path=report_reference.path,
        report_sha256=report_reference.sha256,
        block_count=len(chapter.blocks),
    )


def write_chunk_review(
    config_path: Path,
    project_root: Path,
    chapter_id: str,
) -> ChunkReviewSummary:
    """Write a complete chunking report for one chapter."""

    context = load_stage_context(config_path, project_root)
    store = context.workspace.artifacts
    document = store.read(DOCUMENT_PATH, BookDocument)
    manifest = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    if document.book_id != context.config.book_id or manifest.book_id != context.config.book_id:
        raise ReviewError("stored text artifacts belong to a different book")
    chapter = _resolve_chapter(document, chapter_id)
    chapter_chunks = tuple(
        chunk for chunk in manifest.chunks if chunk.chapter_id == chapter.chapter_id
    )
    if not chapter_chunks:
        raise ReviewError(f"chapter {chapter.chapter_id!r} has no stored chunks")

    report_path = f"{REVIEW_REPORT_DIR}/{chapter.chapter_id}-chunking.md"
    report_reference = store.write_bytes(
        report_path,
        render_chunk_chapter_report(manifest, chapter.chapter_id).encode("utf-8"),
    )
    return ChunkReviewSummary(
        book_id=context.config.book_id,
        chapter_id=chapter.chapter_id,
        report_path=report_reference.path,
        report_sha256=report_reference.sha256,
        block_count=len(chapter.blocks),
        chunk_count=len(chapter_chunks),
    )


def _resolve_chapter(document: BookDocument, chapter_id: str) -> ChapterDocument:
    chapter = next(
        (candidate for candidate in document.chapters if candidate.chapter_id == chapter_id),
        None,
    )
    if chapter is None:
        available = ", ".join(candidate.chapter_id for candidate in document.chapters)
        raise ReviewError(f"unknown chapter {chapter_id!r}; available chapters: {available}")
    return chapter
