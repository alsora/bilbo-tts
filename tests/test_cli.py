from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from bilbo_tts import cli
from bilbo_tts.chunk_service import ChunkSummary
from bilbo_tts.chunking import ChunkingError
from bilbo_tts.doctor import EnvironmentReport
from bilbo_tts.ingest import IngestionError, IngestSummary
from bilbo_tts.models import SourceFormat
from bilbo_tts.normalization import NormalizationError, NormalizeSummary

runner = CliRunner()


def _report(*, healthy: bool = True) -> EnvironmentReport:
    return {
        "healthy": healthy,
        "platform": {
            "system": "Darwin",
            "release": "23.5.0",
            "machine": "arm64",
            "apple_silicon": True,
        },
        "environment": {
            "project_root": "/project",
            "pixi_environment": "default",
            "python_prefix": "/project/.pixi/envs/default",
            "python_managed": healthy,
        },
        "tools": {
            "python": "/project/.pixi/envs/default/bin/python",
            "pixi": "/project/.tools/bin/pixi",
            "ffmpeg": "/project/.pixi/envs/default/bin/ffmpeg",
            "pandoc": "/project/.pixi/envs/default/bin/pandoc",
            "libsndfile": "libsndfile.dylib",
        },
        "caches": {
            "huggingface": "/project/work/cache/huggingface",
            "xdg": "/project/work/cache/xdg",
            "models": "/project/work/cache/models",
        },
        "acceleration": {
            "mlx_installed": False,
        },
    }


def test_doctor_prints_readable_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "collect_environment", _report)

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == 0
    assert "Status: healthy" in result.stdout
    assert "ffmpeg: /project/.pixi/envs/default/bin/ffmpeg" in result.stdout
    assert "mlx_installed: False" in result.stdout


def test_doctor_prints_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "collect_environment", _report)

    result = runner.invoke(cli.app, ["doctor", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["healthy"] is True


def test_doctor_fails_for_unmanaged_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "collect_environment", lambda: _report(healthy=False))

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == 1
    assert "Status: unhealthy" in result.stdout


def test_root_command_shows_help() -> None:
    result = runner.invoke(cli.app)

    assert result.exit_code == 2
    assert "Build reproducible Italian audiobooks." in result.stdout


def test_ingest_prints_machine_readable_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = IngestSummary(
        status="completed",
        book_id="book",
        source_format=SourceFormat.LATEX,
        source_sha256="a" * 64,
        document_path="manifests/book-document.json",
        document_sha256="b" * 64,
        report_path="reports/extraction.md",
        report_sha256="c" * 64,
        chapter_count=1,
        block_count=2,
    )
    monkeypatch.setattr(cli, "ingest_book", lambda _config, _root: summary)

    result = runner.invoke(cli.app, ["ingest", "books/book/book.yaml"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == summary.model_dump(mode="json")


def test_ingest_prints_json_error_and_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_config: object, _root: object) -> None:
        raise IngestionError("source is unusable")

    monkeypatch.setattr(cli, "ingest_book", fail)

    result = runner.invoke(cli.app, ["ingest", "books/book/book.yaml"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"] == "source is unusable"


def test_normalize_prints_machine_readable_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = NormalizeSummary(
        book_id="book",
        document_sha256="a" * 64,
        normalized_path="manifests/normalized-document.json",
        normalized_sha256="b" * 64,
        report_path="reports/normalization.md",
        report_sha256="c" * 64,
        block_count=2,
        transformation_count=1,
        lexicon_application_count=1,
        warning_count=0,
    )
    monkeypatch.setattr(cli, "normalize_book", lambda _config, _root: summary)

    result = runner.invoke(cli.app, ["normalize", "books/book/book.yaml"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == summary.model_dump(mode="json")


def test_normalize_prints_json_error_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_config: object, _root: object) -> None:
        raise NormalizationError("text is unusable")

    monkeypatch.setattr(cli, "normalize_book", fail)

    result = runner.invoke(cli.app, ["normalize", "books/book/book.yaml"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "schema_version": "normalize-summary/v1",
        "status": "failed",
        "error": "text is unusable",
    }


def test_chunk_prints_machine_readable_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = ChunkSummary(
        book_id="book",
        normalized_sha256="a" * 64,
        chunk_manifest_path="manifests/chunk-manifest.json",
        chunk_manifest_sha256="b" * 64,
        report_path="reports/chunking.md",
        report_sha256="c" * 64,
        chunk_count=3,
        max_characters=300,
        largest_chunk_characters=120,
    )
    monkeypatch.setattr(cli, "chunk_book", lambda _config, _root: summary)

    result = runner.invoke(cli.app, ["chunk", "books/book/book.yaml"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == summary.model_dump(mode="json")


def test_chunk_prints_json_error_and_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_config: object, _root: object) -> None:
        raise ChunkingError("chunk is unusable")

    monkeypatch.setattr(cli, "chunk_book", fail)

    result = runner.invoke(cli.app, ["chunk", "books/book/book.yaml"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "schema_version": "chunk-summary/v1",
        "status": "failed",
        "error": "chunk is unusable",
    }
