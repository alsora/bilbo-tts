"""Regenerate reviewed normalization and chunking golden outputs."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from bilbo_tts import cli

ROOT = Path(__file__).parents[2]
BOOKS = ROOT / "tests" / "fixtures" / "books"
GOLDENS = ROOT / "tests" / "fixtures" / "golden"
OUTPUTS = {
    "manifests/normalized-document.json": "normalized-document.json",
    "reports/normalization.md": "normalization.md",
    "manifests/chunk-manifest.json": "chunk-manifest.json",
    "reports/chunking.md": "chunking.md",
}


def main() -> None:
    runner = CliRunner()
    for name in ("tiny-latex", "tiny-pdf"):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            destination = project / "books" / name
            destination.parent.mkdir(parents=True)
            shutil.copytree(BOOKS / name, destination)
            summaries: dict[str, bytes] = {}
            for stage in ("ingest", "normalize", "chunk"):
                result = runner.invoke(
                    cli.app,
                    [
                        stage,
                        f"books/{name}/book.yaml",
                        "--project-root",
                        str(project),
                    ],
                )
                if result.exit_code != 0:
                    raise RuntimeError(f"{name} {stage} failed:\n{result.output}")
                summaries[stage] = result.stdout.encode("utf-8")
            golden = GOLDENS / name
            golden.mkdir(parents=True, exist_ok=True)
            workspace = project / "work" / name
            for source, target in OUTPUTS.items():
                (golden / target).write_bytes((workspace / source).read_bytes())
            (golden / "normalize-summary.json").write_bytes(summaries["normalize"])
            (golden / "chunk-summary.json").write_bytes(summaries["chunk"])


if __name__ == "__main__":
    main()
