"""Command-line interface for the audiobook pipeline."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from bilbo_tts.doctor import EnvironmentReport, collect_environment

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
