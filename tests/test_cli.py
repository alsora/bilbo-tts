from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from bilbo_tts import cli
from bilbo_tts.assembly import AssembleSummary, AssemblyError
from bilbo_tts.chunk_service import ChunkSummary
from bilbo_tts.chunking import ChunkingError
from bilbo_tts.doctor import EnvironmentReport
from bilbo_tts.ingest import IngestionError, IngestSummary
from bilbo_tts.models import SourceFormat
from bilbo_tts.normalization import NormalizationError, NormalizeSummary
from bilbo_tts.review_service import ChunkReviewSummary, ExtractionReviewSummary
from bilbo_tts.synthesis import SynthesisError, SynthesizeSummary
from bilbo_tts.verification import ReviewDecisionSummary, VerifySummary

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
            "ffprobe": "/project/.pixi/envs/default/bin/ffprobe",
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
    assert "ffprobe: /project/.pixi/envs/default/bin/ffprobe" in result.stdout
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


def test_review_extraction_prints_machine_readable_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = ExtractionReviewSummary(
        book_id="book",
        chapter_id="chapter-1",
        report_path="reports/review/chapter-1-extraction.md",
        report_sha256="a" * 64,
        block_count=2,
    )
    monkeypatch.setattr(
        cli,
        "write_extraction_review",
        lambda _config, _root, _chapter: summary,
    )

    result = runner.invoke(
        cli.app,
        ["review-extraction", "books/book/book.yaml", "--chapter", "chapter-1"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == summary.model_dump(mode="json")


def test_review_chunking_prints_machine_readable_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = ChunkReviewSummary(
        book_id="book",
        chapter_id="chapter-1",
        report_path="reports/review/chapter-1-chunking.md",
        report_sha256="a" * 64,
        block_count=2,
        chunk_count=3,
    )
    monkeypatch.setattr(
        cli,
        "write_chunk_review",
        lambda _config, _root, _chapter: summary,
    )

    result = runner.invoke(
        cli.app,
        ["review-chunking", "books/book/book.yaml", "--chapter", "chapter-1"],
    )

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


def test_synthesize_prints_summary_and_forwards_selectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = SynthesizeSummary(
        status="completed",
        book_id="book",
        chunk_manifest_sha256="a" * 64,
        selected_count=1,
        generated_count=1,
        skipped_count=0,
        failed_count=0,
        missing_count=2,
        generation_manifest_path="manifests/generation-manifest.json",
        generation_manifest_sha256="b" * 64,
        report_path="reports/synthesis.md",
        report_sha256="c" * 64,
    )
    arguments: dict[str, object] = {}

    def synthesize(_config: object, _root: object, **kwargs: object) -> SynthesizeSummary:
        arguments.update(kwargs)
        return summary

    monkeypatch.setattr(cli, "synthesize_book", synthesize)
    result = runner.invoke(
        cli.app,
        [
            "synthesize",
            "books/book/book.yaml",
            "--chapter",
            "chapter-1",
            "--chapter",
            "chapter-2",
            "--chunk-start",
            "2",
            "--chunk-end",
            "4",
            "--failed",
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == summary.model_dump(mode="json")
    assert arguments == {
        "chapters": ("chapter-1", "chapter-2"),
        "chunk_start": 2,
        "chunk_end": 4,
        "failed_only": True,
        "force": True,
        "verification_retry": False,
    }


def test_synthesize_prints_json_error_and_partial_status_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_config: object, _root: object, **_kwargs: object) -> None:
        raise SynthesisError("generation is unavailable")

    monkeypatch.setattr(cli, "synthesize_book", fail)
    failed = runner.invoke(cli.app, ["synthesize", "books/book/book.yaml"])
    assert failed.exit_code == 1
    assert json.loads(failed.stdout) == {
        "schema_version": "synthesize-summary/v1",
        "status": "failed",
        "error": "generation is unavailable",
    }

    partial = SynthesizeSummary(
        status="partial",
        book_id="book",
        chunk_manifest_sha256="a" * 64,
        selected_count=2,
        generated_count=1,
        skipped_count=0,
        failed_count=1,
        missing_count=0,
        generation_manifest_path="manifests/generation-manifest.json",
        generation_manifest_sha256="b" * 64,
        report_path="reports/synthesis.md",
        report_sha256="c" * 64,
    )
    monkeypatch.setattr(cli, "synthesize_book", lambda *_args, **_kwargs: partial)
    partial_result = runner.invoke(cli.app, ["synthesize", "books/book/book.yaml"])

    assert partial_result.exit_code == 1
    assert json.loads(partial_result.stdout)["status"] == "partial"


def test_verify_prints_summary_and_forwards_chapter(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = VerifySummary(
        status="completed",
        book_id="book",
        selected_count=1,
        transcribed_count=1,
        reused_count=0,
        accepted_count=1,
        retryable_count=0,
        review_count=0,
        verification_manifest_path="manifests/verification-manifest.json",
        verification_manifest_sha256="a" * 64,
        report_path="reports/verification.md",
        report_sha256="b" * 64,
    )
    arguments: dict[str, object] = {}

    def verify(_config: object, _root: object, **kwargs: object) -> VerifySummary:
        arguments.update(kwargs)
        return summary

    monkeypatch.setattr(cli, "run_verification_loop", verify)
    result = runner.invoke(
        cli.app,
        [
            "verify",
            "books/book/book.yaml",
            "--chapter",
            "chapter-1",
            "--chapter",
            "chapter-2",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == summary.model_dump(mode="json")
    assert arguments == {"chapters": ("chapter-1", "chapter-2")}


def test_verify_pass_forwards_ordered_chapters(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = VerifySummary(
        status="completed",
        book_id="book",
        selected_count=2,
        transcribed_count=2,
        reused_count=0,
        accepted_count=2,
        retryable_count=0,
        review_count=0,
        verification_manifest_path="manifests/verification-manifest.json",
        verification_manifest_sha256="a" * 64,
        report_path="reports/verification.md",
        report_sha256="b" * 64,
    )
    arguments: dict[str, object] = {}

    def verify(_config: object, _root: object, **kwargs: object) -> VerifySummary:
        arguments.update(kwargs)
        return summary

    monkeypatch.setattr(cli, "verify_book_pass", verify)
    result = runner.invoke(
        cli.app,
        [
            "verify-pass",
            "books/book/book.yaml",
            "--chapter",
            "chapter-1",
            "--chapter",
            "chapter-2",
        ],
    )

    assert result.exit_code == 0
    assert arguments == {"chapters": ("chapter-1", "chapter-2")}


def test_verify_review_status_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = VerifySummary(
        status="review",
        book_id="book",
        selected_count=1,
        transcribed_count=1,
        reused_count=0,
        accepted_count=0,
        retryable_count=0,
        review_count=1,
        verification_manifest_path="manifests/verification-manifest.json",
        verification_manifest_sha256="a" * 64,
        report_path="reports/verification.md",
        report_sha256="b" * 64,
    )
    monkeypatch.setattr(cli, "run_verification_loop", lambda *_args, **_kwargs: summary)

    result = runner.invoke(cli.app, ["verify", "books/book/book.yaml"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "review"


def test_assemble_prints_summary_and_forwards_options(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = AssembleSummary(
        status="completed",
        book_id="book",
        selected_count=2,
        reused=False,
        output_path="media/book-chapter-1.m4b",
        output_sha256="a" * 64,
        assembly_manifest_path="manifests/assembly-manifest.json",
        assembly_manifest_sha256="b" * 64,
        report_path="reports/assembly.md",
        report_sha256="c" * 64,
    )
    arguments: dict[str, object] = {}

    def assemble(_config: object, _root: object, **kwargs: object) -> AssembleSummary:
        arguments.update(kwargs)
        return summary

    monkeypatch.setattr(cli, "assemble_book", assemble)
    result = runner.invoke(
        cli.app,
        [
            "assemble",
            "books/book/book.yaml",
            "--chapter",
            "chapter-1",
            "--chapter",
            "chapter-2",
            "--allow-unaccepted",
            "--override-note",
            "Reviewed for this build.",
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == summary.model_dump(mode="json")
    assert arguments == {
        "chapters": ("chapter-1", "chapter-2"),
        "allow_unaccepted": True,
        "override_note": "Reviewed for this build.",
        "force": True,
    }


def test_assemble_prints_json_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssemblyError("audio is not accepted")

    monkeypatch.setattr(cli, "assemble_book", fail)

    result = runner.invoke(cli.app, ["assemble", "books/book/book.yaml"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "schema_version": "assemble-summary/v1",
        "status": "failed",
        "error": "audio is not accepted",
    }


def test_review_verification_requires_auditable_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = ReviewDecisionSummary(
        status="accepted",
        book_id="book",
        chunk_id="chunk-1",
        generation_sha256="a" * 64,
        verification_manifest_sha256="b" * 64,
        report_sha256="c" * 64,
    )
    monkeypatch.setattr(cli, "record_review_decision", lambda *_args, **_kwargs: summary)

    result = runner.invoke(
        cli.app,
        [
            "review-verification",
            "books/book/book.yaml",
            "--chunk",
            "chunk-1",
            "--action",
            "accept",
            "--reviewer",
            "Ada",
            "--note",
            "Listened to the complete chunk.",
        ],
    )
    invalid = runner.invoke(
        cli.app,
        [
            "review-verification",
            "books/book/book.yaml",
            "--chunk",
            "chunk-1",
            "--action",
            "skip",
            "--reviewer",
            "Ada",
            "--note",
            "Not a valid action.",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == summary.model_dump(mode="json")
    assert invalid.exit_code == 1
    assert "--action must be" in json.loads(invalid.stdout)["error"]
