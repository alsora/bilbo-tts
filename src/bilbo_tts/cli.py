"""Command-line interface for the audiobook pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, Never, cast

import typer

from bilbo_tts.artifacts import ArtifactError
from bilbo_tts.assembly import AssemblyError, assemble_book
from bilbo_tts.chunk_service import chunk_book
from bilbo_tts.chunking import ChunkingError
from bilbo_tts.config import ConfigurationError
from bilbo_tts.doctor import EnvironmentReport, collect_environment
from bilbo_tts.ingest import IngestionError, ingest_book
from bilbo_tts.normalization import (
    LexiconError,
    NormalizationError,
    normalize_book,
)
from bilbo_tts.qualification import (
    CandidateConfigurationError,
    CorpusError,
    QualificationError,
    prepare_listening_for_candidates,
    qualify_tts,
    score_tts_asr,
)
from bilbo_tts.qualification.audio import AudioValidationError
from bilbo_tts.review_service import (
    ReviewError,
    write_chunk_review,
    write_extraction_review,
)
from bilbo_tts.serialization import canonical_json_bytes
from bilbo_tts.stages import StageError
from bilbo_tts.synthesis import SynthesisError, synthesize_book
from bilbo_tts.tts import TtsError
from bilbo_tts.verification import (
    VerificationError,
    record_review_decision,
    verify_book_pass,
)
from bilbo_tts.verification_process import run_verification_loop

app = typer.Typer(
    help="Build reproducible Italian audiobooks.",
    no_args_is_help=True,
)
ConfigArgument = Annotated[Path, typer.Argument(help="Path to books/<book-id>/book.yaml.")]
ProjectRootOption = Annotated[
    Path,
    typer.Option("--project-root", help="Project root containing books/ and work/."),
]
ChapterOption = Annotated[
    str,
    typer.Option("--chapter", help="Stable chapter identifier."),
]
CandidateArgument = Annotated[
    str,
    typer.Argument(help="Candidate name: a config/qualification/<name>.yaml stem."),
]
CandidatesArgument = Annotated[
    list[str],
    typer.Argument(help="Two or more qualified candidate names."),
]
SeedOption = Annotated[int, typer.Option("--seed", help="Blind-order randomization seed.")]


@app.callback()
def main() -> None:
    """Build reproducible Italian audiobooks."""


def _format_report(report: EnvironmentReport) -> str:
    lines = [
        f"Status: {'healthy' if report['healthy'] else 'unhealthy'}",
        "",
        "Platform:",
    ]
    lines.extend(f"  {name}: {value}" for name, value in report["platform"].items())
    lines.append("Environment:")
    lines.extend(f"  {name}: {value}" for name, value in report["environment"].items())
    lines.append("Tools:")
    lines.extend(f"  {name}: {value or 'not found'}" for name, value in report["tools"].items())
    lines.append("Caches:")
    lines.extend(f"  {name}: {value}" for name, value in report["caches"].items())
    lines.append("Acceleration:")
    lines.extend(f"  {name}: {value}" for name, value in report["acceleration"].items())
    return "\n".join(lines)


def _fail_stage(schema_version: str, error: Exception) -> Never:
    typer.echo(
        json.dumps(
            {
                "schema_version": schema_version,
                "status": "failed",
                "error": str(error),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    raise typer.Exit(code=1) from error


@app.command()
def doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the report as JSON."),
    ] = False,
) -> None:
    """Report environment isolation and optional acceleration support."""

    report = collect_environment()
    output = json.dumps(report, indent=2, sort_keys=True) if json_output else _format_report(report)
    typer.echo(output)
    if not report["healthy"]:
        raise typer.Exit(code=1)


@app.command()
def ingest(
    config: ConfigArgument,
    project_root: ProjectRootOption = Path("."),
) -> None:
    """Extract a configured LaTeX or born-digital PDF source."""

    try:
        summary = ingest_book(config, project_root)
    except (ArtifactError, ConfigurationError, IngestionError) as error:
        _fail_stage("ingest-summary/v1", error)

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))
    if summary.status == "failed":
        raise typer.Exit(code=1)


@app.command()
def normalize(
    config: ConfigArgument,
    project_root: ProjectRootOption = Path("."),
) -> None:
    """Convert a stored book document into deterministic Italian speech text."""

    try:
        summary = normalize_book(config, project_root)
    except (
        ArtifactError,
        ConfigurationError,
        LexiconError,
        NormalizationError,
        StageError,
    ) as error:
        _fail_stage("normalize-summary/v1", error)

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


@app.command()
def chunk(
    config: ConfigArgument,
    project_root: ProjectRootOption = Path("."),
) -> None:
    """Split normalized speech text into stable synthesis chunks."""

    try:
        summary = chunk_book(config, project_root)
    except (
        ArtifactError,
        ChunkingError,
        ConfigurationError,
        StageError,
    ) as error:
        _fail_stage("chunk-summary/v1", error)

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


@app.command()
def synthesize(
    config: ConfigArgument,
    project_root: ProjectRootOption = Path("."),
    chapter: Annotated[
        list[str] | None,
        typer.Option(
            "--chapter",
            help="Synthesize this chapter; repeat in manifest order for a contiguous scope.",
        ),
    ] = None,
    chunk_start: Annotated[
        int | None,
        typer.Option("--chunk-start", help="First inclusive chunk sequence."),
    ] = None,
    chunk_end: Annotated[
        int | None,
        typer.Option("--chunk-end", help="Last inclusive chunk sequence."),
    ] = None,
    failed_only: Annotated[
        bool,
        typer.Option("--failed", help="Retry only chunks with a current synthesis failure."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Regenerate valid selected chunks."),
    ] = False,
    verification_retry: Annotated[
        bool,
        typer.Option("--verification-retry", hidden=True),
    ] = False,
) -> None:
    """Generate validated, resumable WAV files for configured chunks."""

    try:
        summary = synthesize_book(
            config,
            project_root,
            chapters=tuple(chapter) if chapter else None,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
            failed_only=failed_only,
            force=force,
            verification_retry=verification_retry,
        )
    except (
        ArtifactError,
        CandidateConfigurationError,
        ConfigurationError,
        StageError,
        SynthesisError,
        TtsError,
    ) as error:
        _fail_stage("synthesize-summary/v1", error)

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))
    if summary.status != "completed":
        raise typer.Exit(code=1)


@app.command()
def verify(
    config: ConfigArgument,
    project_root: ProjectRootOption = Path("."),
    chapter: Annotated[
        list[str] | None,
        typer.Option(
            "--chapter",
            help="Verify this chapter; repeat in manifest order for a contiguous scope.",
        ),
    ] = None,
) -> None:
    """Verify generated audio with isolated ASR and bounded TTS retries."""

    try:
        summary = run_verification_loop(
            config,
            project_root,
            chapters=tuple(chapter) if chapter else None,
        )
    except (
        ArtifactError,
        CandidateConfigurationError,
        ConfigurationError,
        StageError,
        VerificationError,
    ) as error:
        _fail_stage("verify-summary/v1", error)
    typer.echo(canonical_json_bytes(summary).decode("utf-8"))
    if summary.status != "completed":
        raise typer.Exit(code=1)


@app.command()
def assemble(
    config: ConfigArgument,
    project_root: ProjectRootOption = Path("."),
    chapter: Annotated[
        list[str] | None,
        typer.Option(
            "--chapter",
            help="Assemble this chapter; repeat in manifest order for a contiguous scope.",
        ),
    ] = None,
    allow_unaccepted: Annotated[
        bool,
        typer.Option(
            "--allow-unaccepted",
            help="Include current generated audio that is not accepted.",
        ),
    ] = False,
    override_note: Annotated[
        str | None,
        typer.Option(
            "--override-note",
            help="Required audit note when including unaccepted audio.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-encode an otherwise valid assembly."),
    ] = False,
) -> None:
    """Assemble verified chunks into a validated chaptered M4B."""

    try:
        summary = assemble_book(
            config,
            project_root,
            chapters=tuple(chapter) if chapter else None,
            allow_unaccepted=allow_unaccepted,
            override_note=override_note,
            force=force,
        )
    except (
        ArtifactError,
        AssemblyError,
        ConfigurationError,
        StageError,
    ) as error:
        _fail_stage("assemble-summary/v1", error)
    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


@app.command("verify-pass", hidden=True)
def verify_pass_command(
    config: ConfigArgument,
    project_root: ProjectRootOption = Path("."),
    chapter: Annotated[
        list[str] | None,
        typer.Option(
            "--chapter",
            help="Verify this chapter; repeat in manifest order for a contiguous scope.",
        ),
    ] = None,
) -> None:
    """Run one verification pass inside the isolated ASR environment."""

    try:
        summary = verify_book_pass(
            config,
            project_root,
            chapters=tuple(chapter) if chapter else None,
        )
    except (
        ArtifactError,
        CandidateConfigurationError,
        ConfigurationError,
        StageError,
        VerificationError,
    ) as error:
        _fail_stage("verify-summary/v1", error)
    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


@app.command("review-verification")
def review_verification_command(
    config: ConfigArgument,
    chunk: Annotated[
        str,
        typer.Option("--chunk", help="Stable chunk identifier requiring review."),
    ],
    action: Annotated[
        str,
        typer.Option("--action", help="Human decision: accept or regenerate."),
    ],
    reviewer: Annotated[
        str,
        typer.Option("--reviewer", help="Person making the review decision."),
    ],
    note: Annotated[
        str,
        typer.Option("--note", help="Non-empty reason for the decision."),
    ],
    project_root: ProjectRootOption = Path("."),
) -> None:
    """Record an explicit generation-bound review decision."""

    if action not in {"accept", "regenerate"}:
        _fail_stage(
            "review-decision-summary/v1",
            VerificationError("--action must be 'accept' or 'regenerate'"),
        )
    try:
        summary = record_review_decision(
            config,
            project_root,
            chunk_id=chunk,
            action=cast(Literal["accept", "regenerate"], action),
            reviewer=reviewer,
            note=note,
        )
    except (
        ArtifactError,
        ConfigurationError,
        StageError,
        VerificationError,
    ) as error:
        _fail_stage("review-decision-summary/v1", error)
    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


@app.command("qualify-tts")
def qualify_tts_command(
    candidate: CandidateArgument,
    project_root: ProjectRootOption = Path("."),
) -> None:
    """Generate qualification WAV files and auditable reports."""

    try:
        summary = qualify_tts(candidate, project_root)
    except (
        ArtifactError,
        CandidateConfigurationError,
        CorpusError,
        QualificationError,
        TtsError,
    ) as error:
        _fail_stage("tts-qualification-summary/v1", error)

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))
    if summary.status != "completed":
        raise typer.Exit(code=1)


@app.command("prepare-tts-listening")
def prepare_tts_listening_command(
    candidates: CandidatesArgument,
    project_root: ProjectRootOption = Path("."),
    seed: SeedOption = 20_260_711,
) -> None:
    """Build a deterministic blinded listening package."""

    try:
        summary = prepare_listening_for_candidates(tuple(candidates), project_root, seed)
    except (ArtifactError, AudioValidationError, QualificationError) as error:
        _fail_stage("tts-listening-summary/v1", error)

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


@app.command("score-tts-asr")
def score_tts_asr_command(
    candidate: CandidateArgument,
    project_root: ProjectRootOption = Path("."),
) -> None:
    """Score one completed TTS qualification in the separate ASR environment."""

    try:
        summary = score_tts_asr(candidate, project_root)
    except (
        ArtifactError,
        CandidateConfigurationError,
        CorpusError,
        QualificationError,
    ) as error:
        _fail_stage("asr-qualification-summary/v1", error)

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))
    if summary.status != "completed":
        raise typer.Exit(code=1)


@app.command("review-extraction")
def review_extraction(
    config: ConfigArgument,
    chapter: ChapterOption,
    project_root: ProjectRootOption = Path("."),
) -> None:
    """Write a complete extraction report for one chapter."""

    try:
        summary = write_extraction_review(config, project_root, chapter)
    except (
        ArtifactError,
        ConfigurationError,
        ReviewError,
        StageError,
    ) as error:
        _fail_stage("extraction-review-summary/v1", error)

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


@app.command("review-chunking")
def review_chunking(
    config: ConfigArgument,
    chapter: ChapterOption,
    project_root: ProjectRootOption = Path("."),
) -> None:
    """Write a complete chunking report for one chapter."""

    try:
        summary = write_chunk_review(config, project_root, chapter)
    except (
        ArtifactError,
        ConfigurationError,
        ReviewError,
        StageError,
    ) as error:
        _fail_stage("chunk-review-summary/v1", error)

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))
