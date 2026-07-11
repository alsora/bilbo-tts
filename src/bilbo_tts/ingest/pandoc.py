"""Small validated boundary around the Pandoc subprocess."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from bilbo_tts.ingest.common import IngestionError


def read_pandoc_ast(
    *,
    from_format: str,
    label: str,
    cwd: Path,
    input_name: str | None = None,
    input_text: str | None = None,
    pandoc_executable: str = "pandoc",
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Run Pandoc and return a JSON object plus non-empty diagnostics."""

    if (input_name is None) == (input_text is None):
        raise ValueError("provide exactly one Pandoc input")
    executable = shutil.which(pandoc_executable)
    if executable is None:
        raise IngestionError(f"Pandoc executable not found: {pandoc_executable}")
    command = [executable, f"--from={from_format}", "--to=json"]
    if input_name is not None:
        command.append(input_name)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise IngestionError(f"cannot run Pandoc for {label}: {error}") from error
    diagnostics = tuple(line.strip() for line in completed.stderr.splitlines() if line.strip())
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "no diagnostic output"
        raise IngestionError(f"Pandoc failed for {label}: {detail}")
    try:
        raw_ast: Any = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise IngestionError(f"Pandoc returned invalid JSON for {label}: {error}") from error
    if not isinstance(raw_ast, dict):
        raise IngestionError(f"Pandoc returned a non-object JSON document for {label}")
    return raw_ast, diagnostics
