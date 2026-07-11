"""Command-line interface for the audiobook pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from bilbo_tts.artifacts import ArtifactError
from bilbo_tts.chunk_service import ChunkingError, chunk_book
from bilbo_tts.config import ConfigurationError
from bilbo_tts.doctor import EnvironmentReport, collect_environment
from bilbo_tts.ingest import IngestionError, ingest_book
from bilbo_tts.normalization import (
    LexiconError,
    NormalizationError,
    normalize_book,
)
from bilbo_tts.serialization import canonical_json_bytes
from bilbo_tts.stages import StageError

app = typer.Typer(
    help="Build reproducible Italian audiobooks.",
    no_args_is_help=True,
)


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
    config: Annotated[
        Path,
        typer.Argument(help="Path to books/<book-id>/book.yaml."),
    ],
    project_root: Annotated[
        Path,
        typer.Option("--project-root", help="Project root containing books/ and work/."),
    ] = Path("."),
) -> None:
    """Extract a configured LaTeX or born-digital PDF source."""

    try:
        summary = ingest_book(config, project_root)
    except (ArtifactError, ConfigurationError, IngestionError) as error:
        typer.echo(
            json.dumps(
                {
                    "schema_version": "ingest-summary/v1",
                    "status": "failed",
                    "error": str(error),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        raise typer.Exit(code=1) from error

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))
    if summary.status == "failed":
        raise typer.Exit(code=1)


@app.command()
def normalize(
    config: Annotated[
        Path,
        typer.Argument(help="Path to books/<book-id>/book.yaml."),
    ],
    project_root: Annotated[
        Path,
        typer.Option("--project-root", help="Project root containing books/ and work/."),
    ] = Path("."),
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
        typer.echo(
            json.dumps(
                {
                    "schema_version": "normalize-summary/v1",
                    "status": "failed",
                    "error": str(error),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        raise typer.Exit(code=1) from error

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


@app.command()
def chunk(
    config: Annotated[
        Path,
        typer.Argument(help="Path to books/<book-id>/book.yaml."),
    ],
    project_root: Annotated[
        Path,
        typer.Option("--project-root", help="Project root containing books/ and work/."),
    ] = Path("."),
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
        typer.echo(
            json.dumps(
                {
                    "schema_version": "chunk-summary/v1",
                    "status": "failed",
                    "error": str(error),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        raise typer.Exit(code=1) from error

    typer.echo(canonical_json_bytes(summary).decode("utf-8"))
