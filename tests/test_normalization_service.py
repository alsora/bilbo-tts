from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from bilbo_tts.artifacts import ArtifactError, ArtifactStore, StaleArtifactError
from bilbo_tts.ingest.service import DOCUMENT_PATH
from bilbo_tts.models import (
    BlockKind,
    BookDocument,
    ChapterDocument,
    DocumentBlock,
    NormalizedDocument,
    SourceFormat,
    SourceLocation,
)
from bilbo_tts.normalization.service import (
    NORMALIZATION_REPORT_PATH,
    NORMALIZED_PATH,
    normalize_book,
)


def _book_document(
    text: str = "L'ETF rende il 5%.",
    *,
    kind: BlockKind = BlockKind.PARAGRAPH,
) -> BookDocument:
    return BookDocument(
        book_id="book",
        source_format=SourceFormat.LATEX,
        source_sha256="a" * 64,
        chapters=(
            ChapterDocument(
                chapter_id="chapter-1",
                order=0,
                title="Capitolo",
                blocks=(
                    DocumentBlock(
                        block_id="block-1",
                        kind=kind,
                        display_text=text,
                        source=SourceLocation(source_path="source/main.tex"),
                    ),
                ),
            ),
        ),
    )


def _project(tmp_path: Path) -> tuple[Path, Path, ArtifactStore]:
    root = tmp_path / "project"
    book_dir = root / "books" / "book"
    book_dir.mkdir(parents=True)
    config_path = book_dir / "book.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "book-config/v1",
                "book_id": "book",
                "language": "it",
                "input": {"format": "latex", "path": "source/main.tex"},
                "metadata": {"title": "Libro", "author": "Ada"},
                "normalization": {"version": "it-v1", "lexicons": []},
                "chunking": {"max_characters": 100},
                "synthesis": {
                    "model_config_path": "config/qualification/fake.yaml",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    store = ArtifactStore(root / "work" / "book")
    return root, config_path, store


def test_normalize_book_writes_dependent_artifact_report_and_summary(tmp_path: Path) -> None:
    root, config_path, store = _project(tmp_path)
    store.write(DOCUMENT_PATH, _book_document())

    summary = normalize_book(config_path, root)

    normalized = store.read(NORMALIZED_PATH, NormalizedDocument)
    report = store.resolve(NORMALIZATION_REPORT_PATH).read_text(encoding="utf-8")
    assert normalized.blocks[0].display_text == "L'ETF rende il 5%."
    assert normalized.blocks[0].spoken_text == "L'et effe rende il cinque per cento."
    assert normalized.book_document_sha256 == store.reference(DOCUMENT_PATH).sha256
    assert summary.block_count == 1
    assert summary.transformation_count == 2
    assert summary.lexicon_application_count == 1
    assert summary.warning_count == 0
    assert "## Transformations by rule" in report
    assert "`lexicon.finance-it.acronimo-etf`: 1 application" in report
    assert "## Blocks requiring review" in report
    assert "L'et effe rende il cinque per cento." in report
    assert "- `percentage`: `5%` → `cinque per cento`" in report
    assert "L'ETF rende il 5%." not in report
    assert "## Applied lexicon entries" not in report


def test_normalization_report_omits_unchanged_warning_free_blocks(tmp_path: Path) -> None:
    root, config_path, store = _project(tmp_path)
    store.write(DOCUMENT_PATH, _book_document("Testo invariato."))

    normalize_book(config_path, root)

    report = store.resolve(NORMALIZATION_REPORT_PATH).read_text(encoding="utf-8")
    assert "- Changed blocks: 0" in report
    assert "- Unchanged, warning-free blocks omitted: 1" in report
    assert "## Blocks requiring review\n\n- None." in report
    assert "Testo invariato." not in report


def test_normalize_book_resolves_latex_ranges_and_three_part_ratios(
    tmp_path: Path,
) -> None:
    source = r"15.000--100.000 \euro; 35--40\%; 50/30/20."
    root, config_path, store = _project(tmp_path)
    store.write(DOCUMENT_PATH, _book_document(source))

    summary = normalize_book(config_path, root)

    normalized = store.read(NORMALIZED_PATH, NormalizedDocument)
    spoken = normalized.blocks[0].spoken_text
    assert spoken == (
        "quindicimila a centomila euro; trentacinque a quaranta per cento; "
        "cinquanta a trenta a venti."
    )
    assert re.search(r"[\\{}%€]", spoken) is None
    assert normalized.blocks[0].warnings == ()
    assert summary.warning_count == 0


def test_normalize_book_resolves_supported_latex_equation_notation(
    tmp_path: Path,
) -> None:
    source = (
        r"\begin{equation} \text{Valore atteso}: "
        r"C_n \approx C_0 \times 99{,}75^n "
        r"\label{eq:valore} \end{equation}"
    )
    root, config_path, store = _project(tmp_path)
    store.write(DOCUMENT_PATH, _book_document(source, kind=BlockKind.EQUATION))

    summary = normalize_book(config_path, root)

    normalized = store.read(NORMALIZED_PATH, NormalizedDocument)
    spoken = normalized.blocks[0].spoken_text
    assert spoken == (
        "Valore atteso: ci con pedice enne circa uguale a ci con pedice zero "
        "per novantanove virgola settantacinque elevato alla enne"
    )
    assert re.search(r"[\\{}%€]", spoken) is None
    assert normalized.blocks[0].warnings == ()
    assert summary.warning_count == 0


def test_normalized_artifact_becomes_stale_when_document_changes(tmp_path: Path) -> None:
    root, config_path, store = _project(tmp_path)
    store.write(DOCUMENT_PATH, _book_document())
    normalize_book(config_path, root)

    store.write(DOCUMENT_PATH, _book_document("Testo cambiato."))

    with pytest.raises(StaleArtifactError, match="upstream artifact changed"):
        store.read(NORMALIZED_PATH, NormalizedDocument)


def test_normalize_requires_the_upstream_document(tmp_path: Path) -> None:
    root, config_path, _ = _project(tmp_path)

    with pytest.raises(ArtifactError, match="does not exist"):
        normalize_book(config_path, root)
