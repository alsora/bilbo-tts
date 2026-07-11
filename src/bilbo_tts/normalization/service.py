"""Normalization orchestration, artifacts, summaries, and review reports."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from bilbo_tts.ingest.service import DOCUMENT_PATH
from bilbo_tts.models import (
    BookDocument,
    ContractModel,
    NonEmptyText,
    NormalizedDocument,
    Sha256,
)
from bilbo_tts.normalization.engine import NormalizationError, normalize_document
from bilbo_tts.normalization.lexicon import LexiconError, load_lexicons
from bilbo_tts.stages import load_stage_context

NORMALIZED_PATH = "manifests/normalized-document.json"
NORMALIZATION_REPORT_PATH = "reports/normalization.md"


class NormalizeSummary(ContractModel):
    """Machine-readable result emitted by the normalize stage."""

    schema_version: Literal["normalize-summary/v1"] = "normalize-summary/v1"
    status: Literal["completed"] = "completed"
    book_id: NonEmptyText
    document_sha256: Sha256
    normalized_path: NonEmptyText
    normalized_sha256: Sha256
    report_path: NonEmptyText
    report_sha256: Sha256
    block_count: int = Field(ge=0)
    transformation_count: int = Field(ge=0)
    lexicon_application_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


def normalize_book(config_path: Path, project_root: Path) -> NormalizeSummary:
    """Normalize one stored BookDocument and persist auditable outputs."""

    context = load_stage_context(config_path, project_root)
    store = context.workspace.artifacts
    document = store.read(DOCUMENT_PATH, BookDocument)
    document_reference = store.reference(DOCUMENT_PATH)
    if document.book_id != context.config.book_id:
        raise NormalizationError(
            f"book document belongs to {document.book_id!r}, expected {context.config.book_id!r}"
        )
    lexicons = load_lexicons(context.book_dir, context.config.normalization.lexicons)
    normalized = normalize_document(
        document,
        normalization_version=context.config.normalization.version,
        lexicons=lexicons,
    )
    normalized_reference = store.write(
        NORMALIZED_PATH,
        normalized,
        dependencies=(document_reference,),
    )
    report = render_normalization_report(normalized)
    report_reference = store.write_bytes(
        NORMALIZATION_REPORT_PATH,
        report.encode("utf-8"),
    )
    transformations = [
        transformation for block in normalized.blocks for transformation in block.transformations
    ]
    return NormalizeSummary(
        book_id=normalized.book_id,
        document_sha256=document_reference.sha256,
        normalized_path=normalized_reference.path,
        normalized_sha256=normalized_reference.sha256,
        report_path=report_reference.path,
        report_sha256=report_reference.sha256,
        block_count=len(normalized.blocks),
        transformation_count=len(transformations),
        lexicon_application_count=sum(
            transformation.rule_id.startswith("lexicon.") for transformation in transformations
        ),
        warning_count=sum(len(block.warnings) for block in normalized.blocks),
    )


def render_normalization_report(document: NormalizedDocument) -> str:
    """Render source, spoken text, transformations, and unresolved warnings."""

    transformations = [
        (block.block_id, transformation)
        for block in document.blocks
        for transformation in block.transformations
    ]
    warnings = [
        (block.block_id, warning) for block in document.blocks for warning in block.warnings
    ]
    lexicon_applications = [
        (block_id, transformation)
        for block_id, transformation in transformations
        if transformation.rule_id.startswith("lexicon.")
    ]
    lines = [
        f"# Normalization report: {document.book_id}",
        "",
        f"- Normalization version: `{document.normalization_version}`",
        f"- Lexicon SHA-256: `{document.lexicon_sha256}`",
        f"- Blocks: {len(document.blocks)}",
        f"- Transformations: {len(transformations)}",
        f"- Warnings: {len(warnings)}",
        "",
        "## Unresolved symbols and warnings",
        "",
    ]
    if warnings:
        lines.extend(f"- `{block_id}`: {warning}" for block_id, warning in warnings)
    else:
        lines.append("- None.")
    lines.extend(["", "## Applied lexicon entries", ""])
    if lexicon_applications:
        lines.extend(
            f"- `{block_id}` — `{item.rule_id}`: `{item.before}` → `{item.after}`"
            for block_id, item in lexicon_applications
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Normalized blocks", ""])
    for block in document.blocks:
        lines.extend(
            [
                f"### `{block.block_id}`",
                "",
                "**Display text**",
                "",
                block.display_text,
                "",
                "**Spoken text**",
                "",
                block.spoken_text,
                "",
                "**Transformations**",
                "",
            ]
        )
        if block.transformations:
            lines.extend(
                f"- `{item.rule_id}`: `{item.before}` → `{item.after}`"
                for item in block.transformations
            )
        else:
            lines.append("- None.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "LexiconError",
    "NORMALIZATION_REPORT_PATH",
    "NORMALIZED_PATH",
    "NormalizationError",
    "NormalizeSummary",
    "normalize_book",
    "render_normalization_report",
]
