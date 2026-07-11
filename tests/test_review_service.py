from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bilbo_tts.chunk_service import chunk_book
from bilbo_tts.ingest.service import ingest_book
from bilbo_tts.normalization.service import normalize_book
from bilbo_tts.review_service import (
    ReviewError,
    write_chunk_review,
    write_extraction_review,
)

FIXTURE_BOOK = Path(__file__).parent / "fixtures" / "books" / "tiny-latex"


def _ingested_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    config = project_root / "books" / "tiny-latex" / "book.yaml"
    config.parent.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE_BOOK, config.parent)
    ingest_book(config, project_root)
    return project_root, config


def test_write_extraction_review_needs_only_ingested_document(tmp_path: Path) -> None:
    project_root, config = _ingested_project(tmp_path)

    summary = write_extraction_review(config, project_root, "chapter-0002")

    workspace = project_root / "work" / "tiny-latex"
    extraction = (workspace / summary.report_path).read_text(encoding="utf-8")
    assert summary.block_count == 10
    assert "`block-000002`" in extraction
    assert "`block-000011`" in extraction
    assert "`block-000012`" not in extraction


def test_write_chunk_review_creates_complete_selected_chapter_report(tmp_path: Path) -> None:
    project_root, config = _ingested_project(tmp_path)
    normalize_book(config, project_root)
    chunk_book(config, project_root)

    summary = write_chunk_review(config, project_root, "chapter-0002")

    workspace = project_root / "work" / "tiny-latex"
    chunking = (workspace / summary.report_path).read_text(encoding="utf-8")
    assert summary.block_count == 10
    assert summary.chunk_count == 10
    assert "`block-000002.s0000.p0000`" in chunking
    assert "`block-000011.s0000.p0000`" in chunking
    assert "`block-000012.s0000.p0000`" not in chunking


def test_write_extraction_review_rejects_unknown_chapter(tmp_path: Path) -> None:
    project_root, config = _ingested_project(tmp_path)

    with pytest.raises(ReviewError, match="unknown chapter"):
        write_extraction_review(config, project_root, "chapter-missing")
