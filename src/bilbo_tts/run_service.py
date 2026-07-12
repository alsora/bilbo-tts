"""Idempotent orchestration across the existing audiobook pipeline stages."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from bilbo_tts.assembly import AssembleSummary, assemble_book
from bilbo_tts.chapter_selection import ChapterSelectionError, select_chapter_ids
from bilbo_tts.chunk_service import CHUNK_MANIFEST_PATH, ChunkSummary, chunk_book
from bilbo_tts.ingest import IngestSummary, ingest_book
from bilbo_tts.ingest.service import DOCUMENT_PATH
from bilbo_tts.models import (
    BookDocument,
    ChunkManifest,
    ChunkRecord,
    ContractModel,
    Identifier,
    NonEmptyText,
    NormalizedBlock,
    NormalizedDocument,
    Sha256,
)
from bilbo_tts.normalization import NormalizeSummary, normalize_book
from bilbo_tts.normalization.service import NORMALIZED_PATH
from bilbo_tts.stages import StageContext, load_stage_context
from bilbo_tts.synthesis import SynthesizeSummary
from bilbo_tts.tts.factory import resolve_book_candidate
from bilbo_tts.verification import VerifySummary
from bilbo_tts.verification_process import run_verification_loop

TEXT_ONLY_REPORT_PATH = "reports/text-only-qualification.md"
RUN_REPORT_PATH = "reports/run.md"
ESTIMATED_SPEECH_RATE_WPM: Literal[150] = 150
SHORT_CHUNK_OUTLIER_CHARACTERS = 20
LONG_CHUNK_OUTLIER_PERCENT = 90

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class RunError(ValueError):
    """The requested pipeline run cannot complete from its current inputs."""


class TextOnlyChapterSummary(ContractModel):
    """Selected-scope text qualification metrics for one chapter."""

    chapter_id: Identifier
    title: NonEmptyText
    block_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    extraction_warning_count: int = Field(ge=0)
    extraction_warnings: tuple[NonEmptyText, ...] = ()
    normalization_warning_count: int = Field(ge=0)
    normalization_warnings: tuple[NonEmptyText, ...] = ()
    unresolved_token_count: int = Field(ge=0)
    unresolved_tokens: tuple[NonEmptyText, ...] = ()
    chunk_outlier_count: int = Field(ge=0)
    chunk_outlier_ids: tuple[Identifier, ...] = ()
    forced_split_count: int = Field(ge=0)
    forced_split_sentence_ids: tuple[Identifier, ...] = ()
    estimated_speech_duration_ms: int = Field(ge=0)
    configured_pause_duration_ms: int = Field(ge=0)
    estimated_total_duration_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def duration_is_consistent(self) -> TextOnlyChapterSummary:
        if self.extraction_warning_count != len(self.extraction_warnings):
            raise ValueError("extraction_warning_count must match extraction_warnings")
        if self.normalization_warning_count != len(self.normalization_warnings):
            raise ValueError("normalization_warning_count must match normalization_warnings")
        if self.unresolved_token_count != len(self.unresolved_tokens):
            raise ValueError("unresolved_token_count must match unresolved_tokens")
        if self.chunk_outlier_count != len(self.chunk_outlier_ids):
            raise ValueError("chunk_outlier_count must match chunk_outlier_ids")
        if (
            self.estimated_total_duration_ms
            != self.estimated_speech_duration_ms + self.configured_pause_duration_ms
        ):
            raise ValueError("estimated total duration must equal speech plus configured pauses")
        return self


class TextOnlySummary(ContractModel):
    """Machine-readable selected-scope text qualification."""

    schema_version: Literal["text-only-summary/v1"] = "text-only-summary/v1"
    status: Literal["completed"] = "completed"
    book_id: Identifier
    chapters: tuple[TextOnlyChapterSummary, ...]
    chapter_count: int = Field(gt=0)
    block_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    chunk_count: int = Field(gt=0)
    exclusion_count: int = Field(ge=0)
    extraction_warning_count: int = Field(ge=0)
    extraction_warnings: tuple[NonEmptyText, ...] = ()
    normalization_warning_count: int = Field(ge=0)
    normalization_warnings: tuple[NonEmptyText, ...] = ()
    unresolved_token_count: int = Field(ge=0)
    unresolved_tokens: tuple[NonEmptyText, ...] = ()
    chunk_outlier_count: int = Field(ge=0)
    chunk_outlier_ids: tuple[Identifier, ...] = ()
    forced_split_count: int = Field(ge=0)
    forced_split_sentence_ids: tuple[Identifier, ...] = ()
    estimated_speech_rate_wpm: Literal[150] = ESTIMATED_SPEECH_RATE_WPM
    estimated_speech_duration_ms: int = Field(ge=0)
    configured_pause_duration_ms: int = Field(ge=0)
    estimated_total_duration_ms: int = Field(ge=0)
    document_sha256: Sha256
    normalized_sha256: Sha256
    chunk_manifest_sha256: Sha256
    report_path: NonEmptyText
    report_sha256: Sha256

    @model_validator(mode="after")
    def aggregates_are_consistent(self) -> TextOnlySummary:
        if self.chapter_count != len(self.chapters):
            raise ValueError("chapter_count must match chapters")
        if self.extraction_warning_count != len(self.extraction_warnings):
            raise ValueError("extraction_warning_count must match extraction_warnings")
        if self.normalization_warning_count != len(self.normalization_warnings):
            raise ValueError("normalization_warning_count must match normalization_warnings")
        if self.unresolved_token_count != len(self.unresolved_tokens):
            raise ValueError("unresolved_token_count must match unresolved_tokens")
        if self.chunk_outlier_count != len(self.chunk_outlier_ids):
            raise ValueError("chunk_outlier_count must match chunk_outlier_ids")
        aggregates = {
            "block_count": sum(chapter.block_count for chapter in self.chapters),
            "word_count": sum(chapter.word_count for chapter in self.chapters),
            "chunk_count": sum(chapter.chunk_count for chapter in self.chapters),
            "normalization_warning_count": sum(
                chapter.normalization_warning_count for chapter in self.chapters
            ),
            "forced_split_count": sum(chapter.forced_split_count for chapter in self.chapters),
            "estimated_speech_duration_ms": sum(
                chapter.estimated_speech_duration_ms for chapter in self.chapters
            ),
            "configured_pause_duration_ms": sum(
                chapter.configured_pause_duration_ms for chapter in self.chapters
            ),
            "estimated_total_duration_ms": sum(
                chapter.estimated_total_duration_ms for chapter in self.chapters
            ),
        }
        for field_name, expected in aggregates.items():
            if getattr(self, field_name) != expected:
                raise ValueError(f"{field_name} must equal its chapter aggregate")
        if (
            self.estimated_total_duration_ms
            != self.estimated_speech_duration_ms + self.configured_pause_duration_ms
        ):
            raise ValueError("estimated total duration must equal speech plus configured pauses")
        return self


class RunSummary(ContractModel):
    """Machine-readable result of a complete orchestrated audiobook run."""

    schema_version: Literal["run-summary/v1"] = "run-summary/v1"
    status: Literal["completed"] = "completed"
    book_id: Identifier
    scope_chapter_ids: tuple[Identifier, ...]
    text_qualification: TextOnlySummary
    synthesis: SynthesizeSummary
    verification: VerifySummary
    assembly: AssembleSummary
    report_path: NonEmptyText
    report_sha256: Sha256
    next_stage: Literal["build-bundle"] = "build-bundle"

    @model_validator(mode="after")
    def completed_stages_and_scope_match(self) -> RunSummary:
        expected_scope = tuple(chapter.chapter_id for chapter in self.text_qualification.chapters)
        if self.scope_chapter_ids != expected_scope:
            raise ValueError("run scope must match the text qualification chapters")
        if {
            self.text_qualification.book_id,
            self.synthesis.book_id,
            self.verification.book_id,
            self.assembly.book_id,
        } != {self.book_id}:
            raise ValueError("all run stages must belong to the same book")
        if self.synthesis.status != "completed" or self.verification.status != "completed":
            raise ValueError("a completed run requires completed synthesis and verification")
        return self


def run_book(
    config_path: Path,
    project_root: Path,
    *,
    chapters: tuple[str, ...] | None = None,
    text_only: bool = False,
    command_runner: CommandRunner = subprocess.run,
    pixi_executable: Path | None = None,
) -> TextOnlySummary | RunSummary:
    """Run ordered stages, reusing every valid artifact already present."""

    ingest_summary = ingest_book(config_path, project_root)
    if ingest_summary.status != "completed":
        raise RunError(
            f"ingestion did not complete: {ingest_summary.error or 'inspect the extraction report'}"
        )
    normalize_summary = normalize_book(config_path, project_root)
    chunk_summary = chunk_book(config_path, project_root)

    context = load_stage_context(config_path, project_root)
    qualification = _qualify_text(
        context,
        chapters,
        ingest_summary,
        normalize_summary,
        chunk_summary,
    )
    if text_only:
        return qualification

    pixi = pixi_executable or _resolve_pixi_executable()
    candidate = resolve_book_candidate(context.config.synthesis, context.workspace.project_root)
    synthesis = _run_synthesis_process(
        context,
        config_path,
        tuple(chapter.chapter_id for chapter in qualification.chapters),
        environment=_tts_environment(candidate.engine),
        pixi_executable=pixi,
        command_runner=command_runner,
    )
    if synthesis.status != "completed":
        raise RunError(
            "synthesis did not complete "
            f"({synthesis.status}; {synthesis.failed_count} failed, "
            f"{synthesis.missing_count} missing); inspect {synthesis.report_path}"
        )

    verification = run_verification_loop(
        config_path,
        context.workspace.project_root,
        chapters=tuple(chapter.chapter_id for chapter in qualification.chapters),
        command_runner=command_runner,
        pixi_executable=pixi,
    )
    if verification.status != "completed":
        raise RunError(
            "verification did not complete "
            f"({verification.status}; {verification.retryable_count} retryable, "
            f"{verification.review_count} requiring review); "
            f"inspect {verification.report_path}"
        )

    assembly = assemble_book(
        config_path,
        context.workspace.project_root,
        chapters=tuple(chapter.chapter_id for chapter in qualification.chapters),
    )
    report_reference = context.workspace.artifacts.write_bytes(
        RUN_REPORT_PATH,
        render_run_report(qualification, synthesis, verification, assembly).encode("utf-8"),
    )
    return RunSummary(
        book_id=context.config.book_id,
        scope_chapter_ids=tuple(chapter.chapter_id for chapter in qualification.chapters),
        text_qualification=qualification,
        synthesis=synthesis,
        verification=verification,
        assembly=assembly,
        report_path=report_reference.path,
        report_sha256=report_reference.sha256,
    )


def render_text_only_report(
    summary: TextOnlySummary,
    *,
    document_warnings: Sequence[str],
    extraction_warnings: Sequence[tuple[str, str, str]],
    normalization_warnings: Sequence[tuple[str, str, str]],
    outliers: Sequence[tuple[str, int, str]],
    forced_splits: Sequence[tuple[str, str, int]],
) -> str:
    """Render deterministic evidence for selected-scope text qualification."""

    lines = [
        f"# Text-only qualification: {summary.book_id}",
        "",
        f"- Selected chapters: {summary.chapter_count}",
        f"- Blocks: {summary.block_count}",
        f"- Words: {summary.word_count}",
        f"- Chunks: {summary.chunk_count}",
        f"- Full-source exclusions: {summary.exclusion_count}",
        f"- Extraction warnings: {summary.extraction_warning_count}",
        f"- Normalization warnings: {summary.normalization_warning_count}",
        f"- Unresolved tokens: {len(summary.unresolved_tokens)}",
        f"- Chunk outliers: {len(summary.chunk_outlier_ids)}",
        f"- Forced intra-sentence splits: {summary.forced_split_count}",
        f"- Estimated speech: {_format_duration(summary.estimated_speech_duration_ms)}",
        f"- Configured pauses: {_format_duration(summary.configured_pause_duration_ms)}",
        f"- Estimated total: {_format_duration(summary.estimated_total_duration_ms)}",
        "",
        "Duration estimate assumption: spoken text is read at a deterministic "
        f"{ESTIMATED_SPEECH_RATE_WPM} words per minute, then every configured chunk pause "
        "in the selected scope is added.",
        "",
        "Chunk outliers are chunks shorter than "
        f"{SHORT_CHUNK_OUTLIER_CHARACTERS} characters or at least "
        f"{LONG_CHUNK_OUTLIER_PERCENT}% of the configured character limit.",
        "",
        "## Selected chapters",
        "",
    ]
    lines.extend(
        f"- `{chapter.chapter_id}` — {chapter.title}: {chapter.block_count} blocks; "
        f"{chapter.word_count} words; {chapter.chunk_count} chunks; "
        f"{chapter.extraction_warning_count} extraction warnings; "
        f"{chapter.normalization_warning_count} normalization warnings; "
        f"{len(chapter.unresolved_tokens)} unresolved tokens; "
        f"{len(chapter.chunk_outlier_ids)} chunk outliers; "
        f"{chapter.forced_split_count} forced splits; "
        f"estimated {_format_duration(chapter.estimated_total_duration_ms)}"
        for chapter in summary.chapters
    )
    lines.extend(["", "## Full-source extraction warnings", ""])
    lines.extend(f"- {warning}" for warning in document_warnings)
    if not document_warnings:
        lines.append("- None.")
    _append_scoped_warnings(lines, "Selected extraction warnings", extraction_warnings)
    _append_scoped_warnings(lines, "Selected normalization warnings", normalization_warnings)

    lines.extend(["", "## Unresolved tokens", ""])
    lines.extend(f"- `{token}`" for token in summary.unresolved_tokens)
    if not summary.unresolved_tokens:
        lines.append("- None.")

    lines.extend(["", "## Chunk outliers", ""])
    lines.extend(
        f"- `{chunk_id}`: {length} characters ({reason})" for chunk_id, length, reason in outliers
    )
    if not outliers:
        lines.append("- None.")

    lines.extend(["", "## Forced intra-sentence splits", ""])
    lines.extend(
        f"- `{chapter_id}` / `{sentence_id}`: {boundary_count} forced "
        f"boundar{'y' if boundary_count == 1 else 'ies'}"
        for chapter_id, sentence_id, boundary_count in forced_splits
    )
    if not forced_splits:
        lines.append("- None.")
    return "\n".join(lines).rstrip() + "\n"


def render_run_report(
    qualification: TextOnlySummary,
    synthesis: SynthesizeSummary,
    verification: VerifySummary,
    assembly: AssembleSummary,
) -> str:
    """Render the deterministic handoff after successful assembly."""

    scope = ", ".join(f"`{chapter.chapter_id}`" for chapter in qualification.chapters)
    return (
        "\n".join(
            [
                f"# Run report: {qualification.book_id}",
                "",
                f"- Scope: {scope}",
                f"- Text qualification: `{qualification.report_path}`",
                f"- Synthesis: {synthesis.selected_count} selected; "
                f"{synthesis.generated_count} generated; {synthesis.skipped_count} reused",
                f"- Verification: {verification.accepted_count} accepted; "
                f"{verification.reused_count} reused",
                f"- Assembly: `{assembly.output_path}`",
                f"- Assembly reused: {'yes' if assembly.reused else 'no'}",
                "",
                "## Next stage",
                "",
                "Build-bundle packaging is intentionally deferred; the validated assembly is the "
                "single handoff input for that future stage.",
            ]
        )
        + "\n"
    )


def _qualify_text(
    context: StageContext,
    chapters: tuple[str, ...] | None,
    ingest_summary: IngestSummary,
    normalize_summary: NormalizeSummary,
    chunk_summary: ChunkSummary,
) -> TextOnlySummary:
    store = context.workspace.artifacts
    document = store.read(DOCUMENT_PATH, BookDocument)
    document_reference = store.reference(DOCUMENT_PATH)
    normalized = store.read(NORMALIZED_PATH, NormalizedDocument)
    normalized_reference = store.reference(NORMALIZED_PATH)
    chunks = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    chunk_reference = store.reference(CHUNK_MANIFEST_PATH)
    if (
        ingest_summary.document_sha256 != document_reference.sha256
        or normalize_summary.normalized_sha256 != normalized_reference.sha256
        or chunk_summary.chunk_manifest_sha256 != chunk_reference.sha256
    ):
        raise RunError("text stage summaries do not reference their current stored artifacts")
    try:
        scope = select_chapter_ids(chunks, chapters)
    except ChapterSelectionError as error:
        raise RunError(str(error)) from error
    if not scope:
        raise RunError("chunk manifest contains no chapters to run")

    chapter_by_id = {chapter.chapter_id: chapter for chapter in document.chapters}
    normalized_by_block = {block.block_id: block for block in normalized.blocks}
    chunks_by_chapter = _group_chunks(chunks.chunks)
    extraction_warnings: list[tuple[str, str, str]] = []
    normalization_warnings: list[tuple[str, str, str]] = []
    all_outliers: list[tuple[str, int, str]] = []
    all_forced_splits: list[tuple[str, str, int]] = []
    chapter_summaries: list[TextOnlyChapterSummary] = []

    for chapter_id in scope:
        try:
            chapter = chapter_by_id[chapter_id]
        except KeyError as error:
            raise RunError(
                f"chunk manifest references chapter {chapter_id!r} missing from the book document"
            ) from error
        chapter_chunks = chunks_by_chapter.get(chapter_id, ())
        normalized_blocks = [
            _normalized_block(normalized_by_block, block.block_id) for block in chapter.blocks
        ]
        chapter_extraction_warnings = [
            (chapter_id, block.block_id, warning)
            for block in chapter.blocks
            for warning in block.warnings
        ]
        chapter_normalization_warnings = [
            (chapter_id, block.block_id, warning)
            for block in normalized_blocks
            for warning in block.warnings
        ]
        unresolved = _unresolved_tokens(normalized_blocks)
        outliers = _chunk_outliers(chapter_chunks, context.config.chunking.max_characters)
        forced_splits = _forced_splits(chapter_id, chapter_chunks)
        word_count = sum(_word_count(chunk.spoken_text) for chunk in chapter_chunks)
        speech_duration_ms = _speech_duration_ms(word_count)
        pause_duration_ms = sum(chunk.pause.duration_ms for chunk in chapter_chunks)
        extraction_warnings.extend(chapter_extraction_warnings)
        normalization_warnings.extend(chapter_normalization_warnings)
        all_outliers.extend(outliers)
        all_forced_splits.extend(forced_splits)
        chapter_summaries.append(
            TextOnlyChapterSummary(
                chapter_id=chapter_id,
                title=chapter.title,
                block_count=len(chapter.blocks),
                word_count=word_count,
                chunk_count=len(chapter_chunks),
                extraction_warning_count=len(chapter_extraction_warnings),
                extraction_warnings=tuple(item[2] for item in chapter_extraction_warnings),
                normalization_warning_count=len(chapter_normalization_warnings),
                normalization_warnings=tuple(item[2] for item in chapter_normalization_warnings),
                unresolved_token_count=len(unresolved),
                unresolved_tokens=unresolved,
                chunk_outlier_count=len(outliers),
                chunk_outlier_ids=tuple(item[0] for item in outliers),
                forced_split_count=sum(item[2] for item in forced_splits),
                forced_split_sentence_ids=tuple(item[1] for item in forced_splits),
                estimated_speech_duration_ms=speech_duration_ms,
                configured_pause_duration_ms=pause_duration_ms,
                estimated_total_duration_ms=speech_duration_ms + pause_duration_ms,
            )
        )

    unresolved_tokens = tuple(
        sorted({token for chapter in chapter_summaries for token in chapter.unresolved_tokens})
    )
    speech_duration_ms = sum(chapter.estimated_speech_duration_ms for chapter in chapter_summaries)
    pause_duration_ms = sum(chapter.configured_pause_duration_ms for chapter in chapter_summaries)
    summary_without_report = {
        "book_id": context.config.book_id,
        "chapters": tuple(chapter_summaries),
        "chapter_count": len(chapter_summaries),
        "block_count": sum(chapter.block_count for chapter in chapter_summaries),
        "word_count": sum(chapter.word_count for chapter in chapter_summaries),
        "chunk_count": sum(chapter.chunk_count for chapter in chapter_summaries),
        "exclusion_count": ingest_summary.exclusion_count,
        "extraction_warning_count": len(document.warnings) + len(extraction_warnings),
        "extraction_warnings": (
            *document.warnings,
            *(warning for _, _, warning in extraction_warnings),
        ),
        "normalization_warning_count": sum(
            chapter.normalization_warning_count for chapter in chapter_summaries
        ),
        "normalization_warnings": tuple(warning for _, _, warning in normalization_warnings),
        "unresolved_token_count": len(unresolved_tokens),
        "unresolved_tokens": unresolved_tokens,
        "chunk_outlier_count": len(all_outliers),
        "chunk_outlier_ids": tuple(item[0] for item in all_outliers),
        "forced_split_count": sum(chapter.forced_split_count for chapter in chapter_summaries),
        "forced_split_sentence_ids": tuple(item[1] for item in all_forced_splits),
        "estimated_speech_duration_ms": speech_duration_ms,
        "configured_pause_duration_ms": pause_duration_ms,
        "estimated_total_duration_ms": speech_duration_ms + pause_duration_ms,
        "document_sha256": document_reference.sha256,
        "normalized_sha256": normalized_reference.sha256,
        "chunk_manifest_sha256": chunk_reference.sha256,
        "report_path": TEXT_ONLY_REPORT_PATH,
        "report_sha256": "0" * 64,
    }
    draft = TextOnlySummary.model_validate(summary_without_report)
    report = render_text_only_report(
        draft,
        document_warnings=document.warnings,
        extraction_warnings=extraction_warnings,
        normalization_warnings=normalization_warnings,
        outliers=all_outliers,
        forced_splits=all_forced_splits,
    )
    report_reference = store.write_bytes(TEXT_ONLY_REPORT_PATH, report.encode("utf-8"))
    return draft.model_copy(update={"report_sha256": report_reference.sha256})


def _run_synthesis_process(
    context: StageContext,
    config_path: Path,
    chapters: tuple[str, ...],
    *,
    environment: str,
    pixi_executable: Path,
    command_runner: CommandRunner,
) -> SynthesizeSummary:
    command = [
        str(pixi_executable),
        "run",
        "-e",
        environment,
        "bilbo",
        "synthesize",
        _config_argument(config_path, context.workspace.project_root),
        "--project-root",
        str(context.workspace.project_root),
    ]
    for chapter in chapters:
        command.extend(["--chapter", chapter])
    try:
        completed = command_runner(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise RunError(f"synthesis process could not start: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic output"
        raise RunError(f"synthesis process failed with exit code {completed.returncode}: {detail}")
    try:
        payload: Any = json.loads(completed.stdout)
        return SynthesizeSummary.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as error:
        raise RunError(f"synthesis process returned an invalid summary: {error}") from error


def _group_chunks(chunks: Sequence[ChunkRecord]) -> dict[str, tuple[ChunkRecord, ...]]:
    grouped: dict[str, list[ChunkRecord]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.chapter_id, []).append(chunk)
    return {chapter_id: tuple(records) for chapter_id, records in grouped.items()}


def _normalized_block(blocks: dict[str, NormalizedBlock], block_id: str) -> NormalizedBlock:
    try:
        return blocks[block_id]
    except KeyError as error:
        raise RunError(f"normalized document is missing source block {block_id!r}") from error


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+(?:['’]\w+)*", text, flags=re.UNICODE))


def _speech_duration_ms(word_count: int) -> int:
    return round(word_count * 60_000 / ESTIMATED_SPEECH_RATE_WPM)


def _unresolved_tokens(blocks: Sequence[NormalizedBlock]) -> tuple[str, ...]:
    unresolved: set[str] = set()
    for block in blocks:
        if not any(warning.startswith("unresolved-") for warning in block.warnings):
            continue
        unresolved.update(re.findall(r"\\[A-Za-z]+|[{}_^<>@#%€$£]", block.spoken_text))
    return tuple(sorted(unresolved))


def _chunk_outliers(
    chunks: Sequence[ChunkRecord],
    max_characters: int,
) -> list[tuple[str, int, str]]:
    long_threshold = math.ceil(max_characters * LONG_CHUNK_OUTLIER_PERCENT / 100)
    outliers: list[tuple[str, int, str]] = []
    for chunk in chunks:
        length = len(chunk.spoken_text)
        if length < SHORT_CHUNK_OUTLIER_CHARACTERS:
            outliers.append((chunk.chunk_id, length, "short"))
        elif length >= long_threshold:
            outliers.append((chunk.chunk_id, length, "near character limit"))
    return outliers


def _forced_splits(
    chapter_id: str,
    chunks: Sequence[ChunkRecord],
) -> list[tuple[str, str, int]]:
    by_sentence: dict[str, int] = {}
    for chunk in chunks:
        by_sentence[chunk.sentence_id] = by_sentence.get(chunk.sentence_id, 0) + 1
    return [
        (chapter_id, sentence_id, count - 1)
        for sentence_id, count in by_sentence.items()
        if count > 1
    ]


def _append_scoped_warnings(
    lines: list[str],
    heading: str,
    warnings: Sequence[tuple[str, str, str]],
) -> None:
    lines.extend(["", f"## {heading}", ""])
    lines.extend(
        f"- `{chapter_id}` / `{block_id}`: {warning}" for chapter_id, block_id, warning in warnings
    )
    if not warnings:
        lines.append("- None.")


def _format_duration(duration_ms: int) -> str:
    total_seconds = duration_ms // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{duration_ms % 1000:03d}"


def _config_argument(config_path: Path, project_root: Path) -> str:
    candidate = config_path.expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return str(candidate.resolve())


def _resolve_pixi_executable() -> Path:
    configured = os.environ.get("PIXI_EXE")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate.resolve()
    discovered = shutil.which("pixi")
    if discovered:
        return Path(discovered).resolve()
    repository_local = Path(__file__).parents[2] / ".tools" / "bin" / "pixi"
    if repository_local.is_file():
        return repository_local.resolve()
    raise RunError("cannot locate Pixi for isolated synthesis; set PIXI_EXE or add pixi to PATH")


def _tts_environment(engine: str) -> str:
    if engine in {"kokoro", "chatterbox"}:
        return engine
    if engine == "fake":
        return "default"
    raise RunError(f"no isolated Pixi environment is configured for TTS engine {engine!r}")
