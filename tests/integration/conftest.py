from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Protocol

import pytest
from typer.testing import CliRunner

from bilbo_tts import cli


class FixtureRunner(Protocol):
    def __call__(self, name: str, stage: str = "ingest") -> tuple[Any, Path]: ...


@pytest.fixture
def run_book_fixture(tmp_path: Path) -> FixtureRunner:
    """Copy a committed fixture book and invoke a real CLI stage."""

    fixtures = Path(__file__).parents[1] / "fixtures" / "books"
    project_root = tmp_path / "project"

    def run(name: str, stage: str = "ingest") -> tuple[Any, Path]:
        destination = project_root / "books" / name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(fixtures / name, destination)
        result = CliRunner().invoke(
            cli.app,
            [
                stage,
                f"books/{name}/book.yaml",
                "--project-root",
                str(project_root),
            ],
        )
        return result, project_root

    return run
