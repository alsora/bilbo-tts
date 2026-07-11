from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.models import ChunkManifest, NormalizedDocument

FixtureRunner = Callable[[str, str], tuple[Any, Path]]


@pytest.mark.parametrize("fixture_name", ["tiny-latex", "tiny-pdf"])
def test_text_pipeline_matches_reviewed_golden_outputs(
    run_book_fixture: object,
    fixture_name: str,
) -> None:
    run = _fixture_runner(run_book_fixture)
    ingest, project_root = run(fixture_name, "ingest")
    normalized, _ = run(fixture_name, "normalize")
    chunked, _ = run(fixture_name, "chunk")

    assert ingest.exit_code == 0, ingest.output
    assert normalized.exit_code == 0, normalized.output
    assert chunked.exit_code == 0, chunked.output
    workspace = project_root / "work" / fixture_name
    store = ArtifactStore(workspace)
    normalized_document = store.read(
        "manifests/normalized-document.json",
        NormalizedDocument,
    )
    manifest = store.read("manifests/chunk-manifest.json", ChunkManifest)
    assert normalized_document.book_id == fixture_name
    assert manifest.book_id == fixture_name
    assert all(chunk.spoken_text for chunk in manifest.chunks)
    assert all(len(chunk.spoken_text) <= 160 for chunk in manifest.chunks)
    for block in normalized_document.blocks:
        reconstructed = " ".join(
            chunk.spoken_text for chunk in manifest.chunks if chunk.paragraph_id == block.block_id
        )
        assert " ".join(reconstructed.split()) == " ".join(block.spoken_text.split())

    golden = Path(__file__).parents[1] / "fixtures" / "golden" / fixture_name
    for generated, reviewed in (
        ("manifests/normalized-document.json", "normalized-document.json"),
        ("reports/normalization.md", "normalization.md"),
        ("manifests/chunk-manifest.json", "chunk-manifest.json"),
        ("reports/chunking.md", "chunking.md"),
    ):
        assert store.resolve(generated).read_bytes() == (golden / reviewed).read_bytes()
    assert normalized.stdout.encode() == (golden / "normalize-summary.json").read_bytes()
    assert chunked.stdout.encode() == (golden / "chunk-summary.json").read_bytes()


def test_text_pipeline_is_byte_idempotent(run_book_fixture: object) -> None:
    run = _fixture_runner(run_book_fixture)
    ingest, project_root = run("tiny-latex", "ingest")
    first_normalize, _ = run("tiny-latex", "normalize")
    first_chunk, _ = run("tiny-latex", "chunk")
    assert ingest.exit_code == first_normalize.exit_code == first_chunk.exit_code == 0
    workspace = project_root / "work" / "tiny-latex"
    paths = (
        workspace / "manifests" / "normalized-document.json",
        workspace / "reports" / "normalization.md",
        workspace / "manifests" / "chunk-manifest.json",
        workspace / "reports" / "chunking.md",
    )
    first_bytes = [path.read_bytes() for path in paths]

    second_normalize, _ = run("tiny-latex", "normalize")
    second_chunk, _ = run("tiny-latex", "chunk")

    assert second_normalize.exit_code == second_chunk.exit_code == 0
    assert json.loads(second_normalize.stdout) == json.loads(first_normalize.stdout)
    assert json.loads(second_chunk.stdout) == json.loads(first_chunk.stdout)
    assert [path.read_bytes() for path in paths] == first_bytes


def test_text_stages_reject_missing_upstream_artifacts(run_book_fixture: object) -> None:
    run = _fixture_runner(run_book_fixture)

    missing_document, _ = run("tiny-latex", "normalize")
    assert missing_document.exit_code == 1
    assert "book-document.json" in json.loads(missing_document.stdout)["error"]

    ingest, _ = run("tiny-latex", "ingest")
    assert ingest.exit_code == 0
    missing_normalized, _ = run("tiny-latex", "chunk")
    assert missing_normalized.exit_code == 1
    assert "normalized-document.json" in json.loads(missing_normalized.stdout)["error"]


def _fixture_runner(value: object) -> FixtureRunner:
    assert callable(value)
    return cast(FixtureRunner, value)
