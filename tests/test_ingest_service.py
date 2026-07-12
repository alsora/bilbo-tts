from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from bilbo_tts.artifacts import BookWorkspace
from bilbo_tts.ingest.common import IngestionError
from bilbo_tts.ingest.service import DOCUMENT_PATH, REPORT_PATH, IngestSummary, ingest_book
from bilbo_tts.models import BlockKind, BookDocument

FIXTURE_BOOK = Path(__file__).parent / "fixtures" / "books" / "tiny-latex"


def _copy_latex_book(project_root: Path) -> Path:
    config = project_root / "books" / "tiny-latex" / "book.yaml"
    config.parent.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE_BOOK, config.parent)
    return config


def test_included_latex_change_invalidates_source_and_artifact_hashes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _copy_latex_book(project_root)

    first = ingest_book(Path("books/tiny-latex/book.yaml"), project_root)
    included = project_root / "books" / "tiny-latex" / "source" / "chapter-two.tex"
    included.write_text(
        included.read_text(encoding="utf-8") + "\n\nUn paragrafo aggiunto.\n",
        encoding="utf-8",
    )
    second = ingest_book(Path("books/tiny-latex/book.yaml"), project_root)

    assert first.status == second.status == "completed"
    assert first.source_sha256 != second.source_sha256
    assert first.document_sha256 != second.document_sha256
    assert second.block_count == first.block_count + 1


def test_extraction_report_is_an_outline_with_exception_details(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config = _copy_latex_book(project_root)

    ingest_book(config, project_root)

    report = (project_root / "work" / "tiny-latex" / REPORT_PATH).read_text(encoding="utf-8")
    assert "## Chapter outline" in report
    assert "`chapter-0002` — 2. Fondamenti" in report
    assert "## Block warnings by reason" in report
    assert "`table-linearized: verify row and column reading order`: 1 occurrence" in report
    assert "## Items requiring review" in report
    assert "Rendimenti annuali Anno Rendimento 2025 5%" in report
    assert "Questa prefazione precede il primo capitolo." not in report


def test_ingestion_excludes_configured_supplementary_blocks(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config = _copy_latex_book(project_root)
    config.write_text(
        config.read_text(encoding="utf-8")
        + "\ningestion:\n"
        + "  exclude_block_kinds: [footnote, table, caption]\n",
        encoding="utf-8",
    )

    summary = ingest_book(config, project_root)

    document = BookWorkspace(project_root, "tiny-latex").artifacts.read(DOCUMENT_PATH, BookDocument)
    kinds = {block.kind for chapter in document.chapters for block in chapter.blocks}
    configured_exclusions = [
        item for item in document.exclusions if item.reason_code == "configured-block-exclusion"
    ]
    assert summary.status == "completed"
    assert not kinds.intersection({BlockKind.FOOTNOTE, BlockKind.TABLE, BlockKind.CAPTION})
    assert len(configured_exclusions) == 3
    assert {item.description.split()[1] for item in configured_exclusions} == {
        "footnote",
        "table",
        "caption",
    }
    report = (project_root / "work" / "tiny-latex" / REPORT_PATH).read_text(encoding="utf-8")
    assert "`configured-block-exclusion` — 3 occurrences" in report
    assert "table-linearized" not in report


def test_config_and_source_paths_must_stay_in_owned_directories(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config = _copy_latex_book(project_root)
    outside_config = tmp_path / "book.yaml"
    shutil.copyfile(config, outside_config)

    with pytest.raises(IngestionError, match="must remain within"):
        ingest_book(outside_config, project_root)

    source = config.parent / "source" / "main.tex"
    outside_source = tmp_path / "outside.tex"
    outside_source.write_text("Outside", encoding="utf-8")
    source.unlink()
    source.symlink_to(outside_source)

    with pytest.raises(IngestionError, match="escapes the book directory"):
        ingest_book(Path("books/tiny-latex/book.yaml"), project_root)


def test_book_id_must_match_configuration_directory(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config = _copy_latex_book(project_root)
    moved = project_root / "books" / "wrong-name"
    config.parent.rename(moved)

    with pytest.raises(IngestionError, match="must match"):
        ingest_book(Path("books/wrong-name/book.yaml"), project_root)


def test_latex_include_cannot_escape_source_directory(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config = _copy_latex_book(project_root)
    outside = config.parent / "outside.tex"
    outside.write_text("Testo esterno.", encoding="utf-8")
    main = config.parent / "source" / "main.tex"
    main.write_text(
        main.read_text(encoding="utf-8") + "\n\\input{../outside.tex}\n",
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="include escapes"):
        ingest_book(Path("books/tiny-latex/book.yaml"), project_root)


def test_ingest_summary_rejects_inconsistent_status_fields() -> None:
    common = {
        "book_id": "book",
        "source_format": "latex",
        "source_sha256": "a" * 64,
        "report_path": "reports/extraction.md",
        "report_sha256": "b" * 64,
    }

    with pytest.raises(ValidationError, match="completed ingestion requires"):
        IngestSummary.model_validate({"status": "completed", **common})
    with pytest.raises(ValidationError, match="failed ingestion requires"):
        IngestSummary.model_validate(
            {
                "status": "failed",
                "document_path": "manifests/book-document.json",
                "document_sha256": "c" * 64,
                "error": "failed",
                **common,
            }
        )
