from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, cast

import pytest

from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.models import BookDocument, SourceFormat


class FixtureRunner(Protocol):
    def __call__(self, name: str, stage: str = "ingest") -> tuple[Any, Path]: ...


@pytest.mark.parametrize(
    ("fixture_name", "source_format"),
    [
        ("tiny-latex", SourceFormat.LATEX),
        ("tiny-pdf", SourceFormat.PDF),
    ],
)
def test_ingest_cli_matches_reviewed_golden_outputs(
    run_book_fixture: object,
    fixture_name: str,
    source_format: SourceFormat,
) -> None:
    run = _fixture_runner(run_book_fixture)
    result, project_root = run(fixture_name)

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["status"] == "completed"
    assert summary["source_format"] == source_format.value

    workspace = project_root / "work" / fixture_name
    store = ArtifactStore(workspace)
    document = store.read("manifests/book-document.json", BookDocument)
    assert document.book_id == fixture_name
    assert document.source_format is source_format
    assert [chapter.order for chapter in document.chapters] == list(range(len(document.chapters)))
    assert all(block.display_text for chapter in document.chapters for block in chapter.blocks)
    assert all(
        block.source.source_path for chapter in document.chapters for block in chapter.blocks
    )

    golden_root = Path(__file__).parents[1] / "fixtures" / "golden" / fixture_name
    assert (
        store.resolve("manifests/book-document.json").read_bytes()
        == (golden_root / "book-document.json").read_bytes()
    )
    assert (
        store.resolve("reports/extraction.md").read_bytes()
        == (golden_root / "extraction.md").read_bytes()
    )


def test_ingest_cli_is_byte_idempotent(run_book_fixture: object) -> None:
    run = _fixture_runner(run_book_fixture)
    first, project_root = run("tiny-latex")
    assert first.exit_code == 0, first.output
    workspace = project_root / "work" / "tiny-latex"
    document_path = workspace / "manifests" / "book-document.json"
    report_path = workspace / "reports" / "extraction.md"
    first_document = document_path.read_bytes()
    first_report = report_path.read_bytes()

    second, _ = run("tiny-latex")

    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout) == json.loads(first.stdout)
    assert document_path.read_bytes() == first_document
    assert report_path.read_bytes() == first_report


def test_ingest_cli_rejects_scanned_pdf_without_partial_document(
    run_book_fixture: object,
) -> None:
    run = _fixture_runner(run_book_fixture)

    result, project_root = run("tiny-scanned")

    assert result.exit_code == 1
    summary = json.loads(result.stdout)
    assert summary["status"] == "failed"
    assert summary["scanned_pages"] == [1]
    workspace = project_root / "work" / "tiny-scanned"
    assert not (workspace / "manifests" / "book-document.json").exists()
    report = (workspace / "reports" / "extraction.md").read_text(encoding="utf-8")
    assert "OCR is deferred" in report
    assert "Scanned or image-only pages: 1" in report


def _fixture_runner(value: object) -> FixtureRunner:
    assert callable(value)
    return cast(FixtureRunner, value)
