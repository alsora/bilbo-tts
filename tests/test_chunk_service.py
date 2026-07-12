from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bilbo_tts.artifacts import ArtifactStore, StaleArtifactError
from bilbo_tts.chunk_service import (
    CHUNK_MANIFEST_PATH,
    CHUNK_REPORT_PATH,
    chunk_book,
)
from bilbo_tts.ingest.service import DOCUMENT_PATH
from bilbo_tts.models import (
    BlockKind,
    BookDocument,
    ChapterDocument,
    ChunkManifest,
    DocumentBlock,
    SourceFormat,
    SourceLocation,
)
from bilbo_tts.normalization import normalize_book
from bilbo_tts.normalization.service import NORMALIZED_PATH


def _document(text: str) -> BookDocument:
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
                        kind=BlockKind.PARAGRAPH,
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
    config = book_dir / "book.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "schema_version": "book-config/v1",
                "book_id": "book",
                "language": "it",
                "input": {"format": "latex", "path": "source/main.tex"},
                "metadata": {"title": "Libro", "author": "Ada"},
                "normalization": {"version": "it-v1", "lexicons": []},
                "chunking": {"max_characters": 30},
                "synthesis": {
                    "model_config_path": "config/qualification/fake.yaml",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return root, config, ArtifactStore(root / "work" / "book")


def test_chunk_book_writes_manifest_report_and_summary(tmp_path: Path) -> None:
    root, config, store = _project(tmp_path)
    store.write(DOCUMENT_PATH, _document("Prima frase. Una seconda frase piuttosto lunga."))
    normalize_book(config, root)

    summary = chunk_book(config, root)

    manifest = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    report = store.resolve(CHUNK_REPORT_PATH).read_text(encoding="utf-8")
    assert summary.chunk_count == len(manifest.chunks)
    assert summary.largest_chunk_characters <= 30
    assert manifest.normalized_document_sha256 == store.reference(NORMALIZED_PATH).sha256
    assert [chunk.sequence for chunk in manifest.chunks] == list(range(len(manifest.chunks)))
    assert "## Forced intra-sentence splits" in report
    assert "- Forced intra-sentence splits: 1" in report
    assert "`block-1`" in report
    assert "⟦SPLIT⟧" in report
    assert "none, 0 ms" in report
    assert "## Ordering, limit, and pause anomalies\n\n- None." in report
    assert "Prima frase." not in report


def test_chunk_report_omits_unsplit_blocks(tmp_path: Path) -> None:
    root, config, store = _project(tmp_path)
    store.write(DOCUMENT_PATH, _document("Breve."))
    normalize_book(config, root)

    chunk_book(config, root)

    report = store.resolve(CHUNK_REPORT_PATH).read_text(encoding="utf-8")
    assert "- Source blocks: 1" in report
    assert "- Forced intra-sentence splits: 0" in report
    assert "## Forced intra-sentence splits\n\n- None." in report
    assert "Breve." not in report


def test_chunk_manifest_becomes_stale_after_renormalization(tmp_path: Path) -> None:
    root, config, store = _project(tmp_path)
    store.write(DOCUMENT_PATH, _document("Prima frase."))
    normalize_book(config, root)
    chunk_book(config, root)

    store.write(DOCUMENT_PATH, _document("Testo cambiato."))
    normalize_book(config, root)

    with pytest.raises(StaleArtifactError, match="upstream artifact changed"):
        store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
