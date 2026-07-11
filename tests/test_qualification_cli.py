from __future__ import annotations

import json
from typing import Literal

import pytest
from typer.testing import CliRunner

from bilbo_tts import cli
from bilbo_tts.qualification.listening import ListeningPackageSummary
from bilbo_tts.qualification.results import QualificationError, TtsQualificationSummary

runner = CliRunner()


def qualification_summary(
    status: Literal["completed", "partial", "failed"] = "completed",
) -> TtsQualificationSummary:
    failure_count = 0 if status == "completed" else 1
    return TtsQualificationSummary(
        status=status,
        engine="fake",
        corpus_sha256="a" * 64,
        sample_count=24,
        completed_count=24 - failure_count,
        failure_count=failure_count,
        result_path="result.json",
        result_sha256="b" * 64,
        report_path="summary.md",
        report_sha256="c" * 64,
    )


def test_qualify_tts_cli_prints_canonical_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = qualification_summary()
    monkeypatch.setattr(cli, "qualify_tts", lambda _engine, _root: summary)

    result = runner.invoke(
        cli.app,
        ["qualify-tts", "fake", "--project-root", "/project"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == summary.model_dump(mode="json")


def test_qualify_tts_cli_returns_nonzero_for_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = qualification_summary("partial")
    monkeypatch.setattr(cli, "qualify_tts", lambda _engine, _root: summary)

    result = runner.invoke(cli.app, ["qualify-tts", "fake"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "partial"


def test_qualify_tts_cli_prints_existing_json_failure_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_engine: object, _root: object) -> None:
        raise QualificationError("candidate is unavailable")

    monkeypatch.setattr(cli, "qualify_tts", fail)
    result = runner.invoke(cli.app, ["qualify-tts", "chatterbox"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "error": "candidate is unavailable",
        "schema_version": "tts-qualification-summary/v1",
        "status": "failed",
    }


def test_prepare_listening_cli_passes_engines_seed_and_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = ListeningPackageSummary(
        seed=123,
        corpus_sha256="a" * 64,
        engine_count=2,
        excerpt_count=24,
        clip_count=48,
        mapping_path="mapping.json",
        mapping_sha256="b" * 64,
        rating_sheet_path="rating-sheet.md",
        rating_sheet_sha256="c" * 64,
    )
    received: list[object] = []

    def prepare(engines: tuple[str, ...], root: object, seed: int) -> ListeningPackageSummary:
        received.extend((engines, root, seed))
        return summary

    monkeypatch.setattr(cli, "prepare_listening_for_engines", prepare)
    result = runner.invoke(
        cli.app,
        [
            "prepare-tts-listening",
            "chatterbox",
            "kokoro",
            "--project-root",
            "/project",
            "--seed",
            "123",
        ],
    )

    assert result.exit_code == 0
    assert received[0] == ("chatterbox", "kokoro")
    assert str(received[1]) == "/project"
    assert received[2] == 123
    assert json.loads(result.stdout) == summary.model_dump(mode="json")


def test_prepare_listening_cli_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_engines: object, _root: object, _seed: object) -> None:
        raise QualificationError("two results are required")

    monkeypatch.setattr(cli, "prepare_listening_for_engines", fail)
    result = runner.invoke(cli.app, ["prepare-tts-listening", "fake"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["schema_version"] == "tts-listening-summary/v1"
