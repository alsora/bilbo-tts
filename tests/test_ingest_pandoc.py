from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bilbo_tts.ingest import pandoc
from bilbo_tts.ingest.common import IngestionError


def test_pandoc_runner_parses_stdin_ast(tmp_path: Path) -> None:
    ast, diagnostics = pandoc.read_pandoc_ast(
        from_format="gfm",
        label="test input",
        cwd=tmp_path,
        input_text="# Titolo\n\nTesto.\n",
    )

    assert diagnostics == ()
    assert [block["t"] for block in ast["blocks"]] == ["Header", "Para"]


def test_pandoc_runner_reports_missing_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bilbo_tts.ingest.pandoc.shutil.which", lambda _name: None)

    with pytest.raises(IngestionError, match="not found"):
        pandoc.read_pandoc_ast(
            from_format="latex",
            label="book",
            cwd=tmp_path,
            input_text="",
        )


@pytest.mark.parametrize(
    ("completed", "message"),
    [
        (
            SimpleNamespace(returncode=2, stdout="", stderr="parse failure"),
            "parse failure",
        ),
        (
            SimpleNamespace(returncode=0, stdout="{broken", stderr=""),
            "invalid JSON",
        ),
        (
            SimpleNamespace(returncode=0, stdout="[]", stderr=""),
            "non-object",
        ),
    ],
)
def test_pandoc_runner_rejects_failed_or_invalid_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    completed: SimpleNamespace,
    message: str,
) -> None:
    monkeypatch.setattr("bilbo_tts.ingest.pandoc.shutil.which", lambda _name: "/pandoc")
    monkeypatch.setattr(
        "bilbo_tts.ingest.pandoc.subprocess.run",
        lambda *_args, **_kwargs: completed,
    )

    with pytest.raises(IngestionError, match=message):
        pandoc.read_pandoc_ast(
            from_format="latex",
            label="book",
            cwd=tmp_path,
            input_text="",
        )


def test_pandoc_runner_reports_process_start_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bilbo_tts.ingest.pandoc.shutil.which", lambda _name: "/pandoc")

    def fail_to_start(*_args: object, **_kwargs: object) -> None:
        raise OSError("cannot execute")

    monkeypatch.setattr("bilbo_tts.ingest.pandoc.subprocess.run", fail_to_start)

    with pytest.raises(IngestionError, match="cannot run Pandoc"):
        pandoc.read_pandoc_ast(
            from_format="latex",
            label="book",
            cwd=tmp_path,
            input_text="",
        )
