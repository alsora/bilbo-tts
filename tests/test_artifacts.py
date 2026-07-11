from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bilbo_tts.artifacts import (
    ArtifactCompatibilityError,
    ArtifactCorruptionError,
    ArtifactError,
    ArtifactOwnershipError,
    ArtifactStore,
    BookWorkspace,
    StaleArtifactError,
)
from bilbo_tts.models import (
    BlockKind,
    BookDocument,
    ChapterDocument,
    DocumentBlock,
    NormalizedDocument,
    SourceFormat,
    SourceLocation,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def book_document(title: str = "Capitolo") -> BookDocument:
    return BookDocument(
        book_id="test-book",
        source_format=SourceFormat.LATEX,
        source_sha256=HASH_A,
        chapters=(
            ChapterDocument(
                chapter_id="chapter-1",
                order=0,
                title=title,
                blocks=(
                    DocumentBlock(
                        block_id="block-1",
                        kind=BlockKind.PARAGRAPH,
                        display_text="Testo.",
                        source=SourceLocation(source_path="book.tex"),
                    ),
                ),
            ),
        ),
    )


def test_artifact_round_trip_is_deterministic(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "work")
    artifact = book_document()

    first_reference = store.write("manifests/book.json", artifact)
    first_bytes = store.resolve(first_reference.path).read_bytes()
    second_reference = store.write("manifests/book.json", artifact)

    assert store.read("manifests/book.json", BookDocument) == artifact
    assert second_reference == first_reference
    assert store.resolve(second_reference.path).read_bytes() == first_bytes
    assert first_bytes.endswith(b"\n")


def test_downstream_artifact_validates_upstream_reference(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    upstream = store.write("book.json", book_document())
    normalized = NormalizedDocument(
        book_id="test-book",
        book_document_sha256=upstream.sha256,
        normalization_version="v1",
        lexicon_sha256=HASH_B,
        blocks=(),
    )
    store.write("normalized.json", normalized, dependencies=(upstream,))

    assert store.read("normalized.json", NormalizedDocument) == normalized

    store.write("book.json", book_document(title="Titolo cambiato"))
    with pytest.raises(StaleArtifactError, match="upstream artifact changed"):
        store.read("normalized.json", NormalizedDocument)


def test_missing_upstream_blocks_read_and_write(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    upstream = store.write("book.json", book_document())
    normalized = NormalizedDocument(
        book_id="test-book",
        book_document_sha256=upstream.sha256,
        normalization_version="v1",
        lexicon_sha256=HASH_B,
        blocks=(),
    )
    store.write("normalized.json", normalized, dependencies=(upstream,))
    store.resolve("book.json").unlink()

    with pytest.raises(StaleArtifactError, match="upstream artifact is missing"):
        store.read("normalized.json", NormalizedDocument)
    with pytest.raises(StaleArtifactError, match="upstream artifact is missing"):
        store.write("another.json", normalized, dependencies=(upstream,))


def test_payload_corruption_and_wrong_contract_are_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.write("book.json", book_document())
    target = store.resolve("book.json")
    envelope = json.loads(target.read_bytes())
    envelope["payload"]["book_id"] = "tampered"
    target.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ArtifactCorruptionError, match="payload checksum mismatch"):
        store.read("book.json", BookDocument)
    with pytest.raises(ArtifactCorruptionError, match="payload checksum mismatch"):
        store.reference("book.json")

    store.write("book.json", book_document())
    with pytest.raises(ArtifactCompatibilityError, match="expected normalized-document"):
        store.read("book.json", NormalizedDocument)


def test_invalid_envelope_is_reported_as_corruption(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    target = store.resolve("broken.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{broken", encoding="utf-8")

    with pytest.raises(ArtifactCorruptionError, match="invalid artifact envelope"):
        store.read("broken.json", BookDocument)


def test_interrupted_replace_preserves_previous_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path)
    original = book_document()
    store.write("book.json", original)

    def fail_replace(_source: os.PathLike[str], _target: os.PathLike[str]) -> None:
        raise OSError("simulated interruption")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(ArtifactError, match="cannot atomically write"):
        store.write("book.json", book_document(title="Replacement"))

    assert store.read("book.json", BookDocument) == original
    assert list(tmp_path.glob(".book.json.*.tmp")) == []


@pytest.mark.parametrize("path", ["/absolute.json", "../escape.json", "a/../../escape.json"])
def test_artifact_paths_cannot_escape_workspace(tmp_path: Path, path: str) -> None:
    store = ArtifactStore(tmp_path / "workspace")

    with pytest.raises(ArtifactOwnershipError, match="must stay within"):
        store.resolve(path)


def test_symlink_cannot_redirect_artifacts_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "link").symlink_to(outside, target_is_directory=True)
    store = ArtifactStore(workspace)

    with pytest.raises(ArtifactOwnershipError, match="escapes"):
        store.write("link/book.json", book_document())


def test_book_workspace_owns_expected_path(tmp_path: Path) -> None:
    workspace = BookWorkspace(tmp_path, "finance-book")

    assert workspace.root == tmp_path / "work" / "finance-book"
    with pytest.raises(ValueError):
        BookWorkspace(tmp_path, "../outside")


def test_raw_report_bytes_are_written_atomically_and_deterministically(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    data = b"# Report\n\nReviewed.\n"

    first = store.write_bytes("reports/extraction.md", data)
    second = store.write_bytes("reports/extraction.md", data)

    assert first == second
    assert store.resolve(first.path).read_bytes() == data
