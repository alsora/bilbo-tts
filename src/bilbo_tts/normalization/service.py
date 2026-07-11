"""Normalization orchestration, artifacts, summaries, and review reports."""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
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
from bilbo_tts.normalization.lexicon import load_lexicons
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
        book_document_sha256=document_reference.sha256,
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
    """Render a compact human-review view of normalization decisions."""

    transformations = [
        (block.block_id, transformation)
        for block in document.blocks
        for transformation in block.transformations
    ]
    warnings = [
        (block.block_id, warning) for block in document.blocks for warning in block.warnings
    ]
    rule_counts = Counter(item.rule_id for _, item in transformations)
    warning_counts = Counter(warning for _, warning in warnings)
    review_blocks = [block for block in document.blocks if block.transformations or block.warnings]
    changed_block_count = sum(block.display_text != block.spoken_text for block in document.blocks)
    lexicon_application_count = sum(
        count for rule_id, count in rule_counts.items() if rule_id.startswith("lexicon.")
    )
    omitted_block_count = len(document.blocks) - len(review_blocks)
    lines = [
        f"# Normalization report: {document.book_id}",
        "",
        f"- Normalization version: `{document.normalization_version}`",
        f"- Lexicon SHA-256: `{document.lexicon_sha256}`",
        f"- Blocks: {len(document.blocks)}",
        f"- Changed blocks: {changed_block_count}",
        f"- Transformations: {len(transformations)}",
        f"- Lexicon applications: {lexicon_application_count}",
        f"- Warnings: {len(warnings)}",
        f"- Unchanged, warning-free blocks omitted: {omitted_block_count}",
        "",
        "## Warnings by reason",
        "",
    ]
    if warning_counts:
        lines.extend(
            f"- `{warning}`: {count} occurrence{'s' if count != 1 else ''}"
            for warning, count in sorted(warning_counts.items())
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Transformations by rule", ""])
    if rule_counts:
        lines.extend(
            f"- `{rule_id}`: {count} application{'s' if count != 1 else ''}"
            for rule_id, count in sorted(rule_counts.items())
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Blocks requiring review", ""])
    if not review_blocks:
        lines.extend(["- None.", ""])
    for block in review_blocks:
        lines.extend([f"### `{block.block_id}`", ""])
        if block.warnings:
            lines.append(
                "- Warnings: " + ", ".join(_inline_code(warning) for warning in block.warnings)
            )
            lines.append("")
        lines.extend(["**Spoken text**", "", block.spoken_text, ""])
        if block.transformations:
            lines.extend(["**Changes**", ""])
            for transformation in block.transformations:
                changes = "; ".join(
                    _render_minimal_changes(transformation.before, transformation.after)
                )
                lines.append(f"- {_inline_code(transformation.rule_id)}: {changes}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_TOKEN_PATTERN = re.compile(r"\w+(?:['’]\w+)*|[^\w\s]", re.UNICODE)


def _render_minimal_changes(before: str, after: str) -> list[str]:
    """Render only the token spans changed by one normalization rule."""

    before_tokens = list(_TOKEN_PATTERN.finditer(before))
    after_tokens = list(_TOKEN_PATTERN.finditer(after))
    matcher = SequenceMatcher(
        a=[token.group() for token in before_tokens],
        b=[token.group() for token in after_tokens],
        autojunk=False,
    )
    lines: list[str] = []
    for operation, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        removed = _token_slice(before, before_tokens, before_start, before_end)
        added = _token_slice(after, after_tokens, after_start, after_end)
        if operation == "insert":
            lines.append(f"added {_inline_code(added)}")
        elif operation == "delete":
            lines.append(f"removed {_inline_code(removed)}")
        else:
            lines.append(f"{_inline_code(removed)} → {_inline_code(added)}")
    if not lines:
        lines.append("whitespace normalized")
    return lines


def _token_slice(text: str, tokens: list[re.Match[str]], start: int, end: int) -> str:
    if start == end:
        return ""
    return text[tokens[start].start() : tokens[end - 1].end()]


def _inline_code(value: str) -> str:
    longest_fence = max((len(match.group()) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * (longest_fence + 1)
    padding = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{padding}{value}{padding}{fence}"
