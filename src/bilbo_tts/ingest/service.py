"""Ingestion orchestration, owned outputs, and review reporting."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from bilbo_tts.artifacts import BookWorkspace
from bilbo_tts.config import BookConfig, load_book_config
from bilbo_tts.ingest.common import IngestionError, MappedContent, assemble_document
from bilbo_tts.ingest.latex import extract_latex
from bilbo_tts.ingest.pdf import ScannedPdfError, extract_pdf
from bilbo_tts.models import (
    BlockKind,
    BookDocument,
    ChapterDocument,
    ContractModel,
    ExclusionRecord,
    NonEmptyText,
    Sha256,
    SourceFormat,
    SourceLocation,
)
from bilbo_tts.serialization import canonical_sha256, sha256_bytes

DOCUMENT_PATH = "manifests/book-document.json"
REPORT_PATH = "reports/extraction.md"


class IngestSummary(ContractModel):
    """Machine-readable result emitted by the ingest stage."""

    schema_version: Literal["ingest-summary/v1"] = "ingest-summary/v1"
    status: Literal["completed", "failed"]
    book_id: NonEmptyText
    source_format: SourceFormat
    source_sha256: Sha256
    document_path: NonEmptyText | None = None
    document_sha256: Sha256 | None = None
    report_path: NonEmptyText
    report_sha256: Sha256
    chapter_count: int = Field(default=0, ge=0)
    block_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    exclusion_count: int = Field(default=0, ge=0)
    scanned_pages: tuple[int, ...] = ()
    error: NonEmptyText | None = None

    @model_validator(mode="after")
    def status_fields_are_consistent(self) -> Self:
        has_document = self.document_path is not None and self.document_sha256 is not None
        if self.status == "completed" and (not has_document or self.error is not None):
            raise ValueError("completed ingestion requires a document and no error")
        if self.status == "failed" and (has_document or self.error is None):
            raise ValueError("failed ingestion requires an error and no document")
        return self


def ingest_book(config_path: Path, project_root: Path) -> IngestSummary:
    """Run one configured source through its adapter and persist owned outputs."""

    root = project_root.expanduser().resolve()
    resolved_config = _resolve_config(config_path, root)
    config = load_book_config(resolved_config)
    book_dir = resolved_config.parent
    if book_dir.name != config.book_id:
        raise IngestionError(
            f"book_id {config.book_id!r} must match configuration directory {book_dir.name!r}"
        )
    source_path = _resolve_source(book_dir, config)
    source_sha256 = _source_checksum(source_path, config)
    workspace = BookWorkspace(root, config.book_id)

    try:
        contents: tuple[MappedContent, ...]
        if config.input.format is SourceFormat.LATEX:
            contents = (extract_latex(source_path, config.input.path),)
        else:
            contents = extract_pdf(source_path, config.input.path)
    except ScannedPdfError as error:
        report = _render_failed_report(config, source_sha256, error)
        report_reference = workspace.artifacts.write_bytes(REPORT_PATH, report.encode("utf-8"))
        return IngestSummary(
            status="failed",
            book_id=config.book_id,
            source_format=config.input.format,
            source_sha256=source_sha256,
            report_path=report_reference.path,
            report_sha256=report_reference.sha256,
            scanned_pages=error.pages,
            error=str(error),
        )

    document = assemble_document(
        book_id=config.book_id,
        source_format=config.input.format,
        source_sha256=source_sha256,
        fallback_title=config.metadata.title,
        contents=contents,
    )
    document_reference = workspace.artifacts.write(DOCUMENT_PATH, document)
    report = render_extraction_report(document)
    report_reference = workspace.artifacts.write_bytes(REPORT_PATH, report.encode("utf-8"))
    return _completed_summary(document, document_reference.sha256, report_reference.sha256)


def render_extraction_report(document: BookDocument) -> str:
    """Render a compact full-book outline and exceptional review items."""

    block_count = sum(len(chapter.blocks) for chapter in document.chapters)
    block_warning_counts = Counter(
        warning
        for chapter in document.chapters
        for block in chapter.blocks
        for warning in block.warnings
    )
    warning_count = len(document.warnings) + sum(block_warning_counts.values())
    review_chapters = [
        (
            chapter,
            [
                block
                for block in chapter.blocks
                if block.kind is not BlockKind.PARAGRAPH or block.warnings
            ],
        )
        for chapter in document.chapters
    ]
    lines = [
        f"# Extraction report: {document.book_id}",
        "",
        f"- Source format: `{document.source_format.value}`",
        f"- Source SHA-256: `{document.source_sha256}`",
        f"- Chapters: {len(document.chapters)}",
        f"- Blocks: {block_count}",
        f"- Warnings: {warning_count}",
        f"- Exclusions: {len(document.exclusions)}",
        "",
        "## Document warnings",
        "",
    ]
    if not document.warnings:
        lines.append("- None.")
    else:
        lines.extend(f"- {warning}" for warning in document.warnings)

    lines.extend(["", "## Block warnings by reason", ""])
    if block_warning_counts:
        lines.extend(
            f"- `{warning}`: {count} occurrence{'s' if count != 1 else ''}"
            for warning, count in sorted(block_warning_counts.items())
        )
    else:
        lines.append("- None.")

    lines.extend(["", "## Exclusions by reason", ""])
    exclusions_by_reason = _group_exclusions(document)
    if not exclusions_by_reason:
        lines.append("- None.")
    else:
        for reason_code, exclusions in exclusions_by_reason.items():
            lines.extend(
                [
                    f"### `{reason_code}` — {len(exclusions)} "
                    f"occurrence{'s' if len(exclusions) != 1 else ''}",
                    "",
                ]
            )
            lines.extend(
                f"- {_format_source(item.source)}: {item.description}" for item in exclusions
            )
            lines.append("")

    lines.extend(["", "## Chapter outline", ""])
    for chapter in document.chapters:
        kind_counts = Counter(block.kind.value for block in chapter.blocks)
        block_range = (
            f"`{chapter.blocks[0].block_id}`–`{chapter.blocks[-1].block_id}`"
            if chapter.blocks
            else "no blocks"
        )
        chapter_warning_count = sum(len(block.warnings) for block in chapter.blocks)
        lines.extend(
            [
                f"- `{chapter.chapter_id}` — {chapter.order + 1}. {chapter.title}: "
                f"{_count_label(len(chapter.blocks), 'block')} ({block_range}); "
                f"{_format_counts(kind_counts)}; "
                f"{_count_label(chapter_warning_count, 'warning')}",
                "",
            ]
        )

    lines.extend(["## Items requiring review", ""])
    if not any(blocks for _, blocks in review_chapters):
        lines.extend(["- None.", ""])
    for chapter, blocks in review_chapters:
        if not blocks:
            continue
        lines.extend([f"### {chapter.order + 1}. {chapter.title}", ""])
        for block in blocks:
            lines.extend(
                [
                    f"#### `{block.block_id}` — {block.kind.value} — "
                    f"{_format_source(block.source)}",
                    "",
                ]
            )
            if block.warnings:
                lines.append(
                    "- Warnings: " + ", ".join(f"`{warning}`" for warning in block.warnings)
                )
                lines.append("")
            lines.extend([block.display_text, ""])
    return "\n".join(lines).rstrip() + "\n"


def render_extraction_chapter_report(
    document: BookDocument,
    chapter: ChapterDocument,
) -> str:
    """Render every extracted block in one selected chapter."""

    warning_count = sum(len(block.warnings) for block in chapter.blocks)
    lines = [
        f"# Extraction chapter review: {chapter.title}",
        "",
        f"- Book: `{document.book_id}`",
        f"- Chapter: `{chapter.chapter_id}`",
        f"- Blocks: {len(chapter.blocks)}",
        f"- Warnings: {warning_count}",
        "",
    ]
    for block in chapter.blocks:
        lines.extend(
            [
                f"## `{block.block_id}` — {block.kind.value} — {_format_source(block.source)}",
                "",
            ]
        )
        if block.warnings:
            lines.append("- Warnings: " + ", ".join(f"`{warning}`" for warning in block.warnings))
            lines.append("")
        lines.extend([block.display_text, ""])
    return "\n".join(lines).rstrip() + "\n"


def _group_exclusions(document: BookDocument) -> dict[str, list[ExclusionRecord]]:
    grouped: dict[str, list[ExclusionRecord]] = {}
    for exclusion in document.exclusions:
        grouped.setdefault(exclusion.reason_code, []).append(exclusion)
    return grouped


def _format_counts(counts: Counter[str]) -> str:
    if not counts:
        return "no block kinds"
    return ", ".join(f"{kind}: {count}" for kind, count in sorted(counts.items()))


def _count_label(count: int, noun: str) -> str:
    return f"{count} {noun}{'s' if count != 1 else ''}"


def _resolve_config(config_path: Path, project_root: Path) -> Path:
    candidate = config_path.expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise IngestionError(f"cannot resolve book configuration {candidate}: {error}") from error
    books_root = (project_root / "books").resolve()
    if not resolved.is_relative_to(books_root):
        raise IngestionError(f"book configuration must remain within {books_root}: {resolved}")
    if not resolved.is_file():
        raise IngestionError(f"book configuration is not a file: {resolved}")
    return resolved


def _resolve_source(book_dir: Path, config: BookConfig) -> Path:
    candidate = book_dir.joinpath(*Path(config.input.path).parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise IngestionError(f"cannot resolve configured source {candidate}: {error}") from error
    if not resolved.is_relative_to(book_dir.resolve()):
        raise IngestionError(f"configured source escapes the book directory: {config.input.path}")
    if not resolved.is_file():
        raise IngestionError(f"configured source is not a file: {resolved}")
    return resolved


def _source_checksum(source_path: Path, config: BookConfig) -> str:
    if config.input.format is SourceFormat.PDF:
        try:
            return sha256_bytes(source_path.read_bytes())
        except OSError as error:
            raise IngestionError(f"cannot read configured source {source_path}: {error}") from error

    source_root = source_path.parent
    files: list[dict[str, str]] = []
    for path in sorted(source_root.rglob("*")):
        if path.is_symlink():
            raise IngestionError(f"LaTeX source tree contains a symlink: {path}")
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError as error:
            raise IngestionError(f"cannot read LaTeX source file {path}: {error}") from error
        digest = sha256_bytes(data)
        files.append({"path": path.relative_to(source_root).as_posix(), "sha256": digest})
    if not files:
        raise IngestionError(f"LaTeX source tree contains no files: {source_root}")
    return canonical_sha256({"entry_point": source_path.name, "files": files})


def _completed_summary(
    document: BookDocument,
    document_sha256: str,
    report_sha256: str,
) -> IngestSummary:
    block_count = sum(len(chapter.blocks) for chapter in document.chapters)
    warning_count = len(document.warnings) + sum(
        len(block.warnings) for chapter in document.chapters for block in chapter.blocks
    )
    return IngestSummary(
        status="completed",
        book_id=document.book_id,
        source_format=document.source_format,
        source_sha256=document.source_sha256,
        document_path=DOCUMENT_PATH,
        document_sha256=document_sha256,
        report_path=REPORT_PATH,
        report_sha256=report_sha256,
        chapter_count=len(document.chapters),
        block_count=block_count,
        warning_count=warning_count,
        exclusion_count=len(document.exclusions),
    )


def _render_failed_report(
    config: BookConfig,
    source_sha256: str,
    error: ScannedPdfError,
) -> str:
    pages = ", ".join(str(page) for page in error.pages)
    return "\n".join(
        [
            f"# Extraction report: {config.book_id}",
            "",
            "- Status: failed",
            f"- Source format: `{config.input.format.value}`",
            f"- Source SHA-256: `{source_sha256}`",
            f"- Scanned or image-only pages: {pages}",
            "",
            "OCR is deferred and no partial canonical document was written.",
            "",
        ]
    )


def _format_source(source: SourceLocation) -> str:
    if source.page is not None:
        return f"`{source.source_path}`, page {source.page}"
    if source.start_line is not None:
        return f"`{source.source_path}`, lines {source.start_line}-{source.end_line}"
    return f"`{source.source_path}`"
