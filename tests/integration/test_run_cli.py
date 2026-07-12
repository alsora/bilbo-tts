from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from bilbo_tts import cli


def _project(tmp_path: Path) -> tuple[Path, Path]:
    fixture = Path(__file__).parents[1] / "fixtures" / "books" / "tiny-latex"
    root = tmp_path / "project"
    destination = root / "books" / "tiny-latex"
    destination.parent.mkdir(parents=True)
    shutil.copytree(fixture, destination)
    return root, destination / "book.yaml"


def test_run_text_only_cli_qualifies_scope_and_reruns_identically(tmp_path: Path) -> None:
    root, config_path = _project(tmp_path)
    arguments = [
        "run",
        str(config_path),
        "--project-root",
        str(root),
        "--chapter",
        "chapter-0002",
        "--chapter",
        "chapter-0003",
        "--text-only",
    ]

    first = CliRunner().invoke(cli.app, arguments)
    report_path = root / "work" / "tiny-latex" / "reports" / "text-only-qualification.md"
    first_report = report_path.read_bytes()
    second = CliRunner().invoke(cli.app, arguments)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_summary = json.loads(first.stdout)
    assert first_summary == json.loads(second.stdout)
    assert first_summary["schema_version"] == "text-only-summary/v1"
    assert [chapter["chapter_id"] for chapter in first_summary["chapters"]] == [
        "chapter-0002",
        "chapter-0003",
    ]
    assert [chapter["title"] for chapter in first_summary["chapters"]] == [
        "Fondamenti",
        "Applicazioni",
    ]
    assert first_summary["estimated_speech_rate_wpm"] == 150
    assert report_path.read_bytes() == first_report


def test_run_text_only_cli_reports_unknown_scope_as_json(tmp_path: Path) -> None:
    root, config_path = _project(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        [
            "run",
            str(config_path),
            "--project-root",
            str(root),
            "--chapter",
            "unknown",
            "--text-only",
        ],
    )

    assert result.exit_code == 1
    error = json.loads(result.stdout)
    assert error["schema_version"] == "text-only-summary/v1"
    assert error["status"] == "failed"
    assert "does not exist" in error["error"]
