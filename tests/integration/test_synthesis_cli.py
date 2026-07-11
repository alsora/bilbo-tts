from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import yaml

from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.models import GenerationManifest
from bilbo_tts.qualification.audio import validate_wav_file
from bilbo_tts.serialization import sha256_bytes
from bilbo_tts.synthesis import GENERATION_MANIFEST_PATH

FixtureRunner = Callable[[str, str], tuple[Any, Path]]


def test_synthesis_cli_writes_valid_sidecars_and_is_a_noop_on_rerun(
    run_book_fixture: object,
) -> None:
    run = _fixture_runner(run_book_fixture)
    for stage in ("ingest", "normalize", "chunk"):
        result, project_root = run("tiny-latex", stage)
        assert result.exit_code == 0, result.output

    first, _ = run("tiny-latex", "synthesize")
    workspace = project_root / "work" / "tiny-latex"
    store = ArtifactStore(workspace)
    manifest = store.read(GENERATION_MANIFEST_PATH, GenerationManifest)
    manifest_bytes = store.resolve(GENERATION_MANIFEST_PATH).read_bytes()
    wav_bytes = {
        record.output_path: store.resolve(record.output_path).read_bytes()
        for record in manifest.records
    }

    assert first.exit_code == 0, first.output
    assert json.loads(first.stdout)["generated_count"] == len(manifest.records)
    assert manifest.failures == ()
    assert manifest.missing_chunk_ids == ()
    for record in manifest.records:
        metadata = validate_wav_file(
            store.resolve(record.output_path),
            expected_sample_rate_hz=record.sample_rate_hz,
        )
        assert metadata.frame_count == record.frame_count
        assert sha256_bytes(store.resolve(record.output_path).read_bytes()) == record.output_sha256
        sidecar_path = Path(record.output_path).with_suffix(".json").as_posix()
        assert store.read(sidecar_path, type(record)) == record

    second, _ = run("tiny-latex", "synthesize")

    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout)["generated_count"] == 0
    assert json.loads(second.stdout)["skipped_count"] == len(manifest.records)
    assert store.resolve(GENERATION_MANIFEST_PATH).read_bytes() == manifest_bytes
    assert {
        record.output_path: store.resolve(record.output_path).read_bytes()
        for record in store.read(GENERATION_MANIFEST_PATH, GenerationManifest).records
    } == wav_bytes


def test_lexicon_edit_regenerates_only_chunks_with_changed_spoken_text(
    run_book_fixture: object,
) -> None:
    run = _fixture_runner(run_book_fixture)
    for stage in ("ingest", "normalize", "chunk", "synthesize"):
        result, project_root = run("tiny-latex", stage)
        assert result.exit_code == 0, result.output
    store = ArtifactStore(project_root / "work" / "tiny-latex")
    before = {
        record.chunk_id: record
        for record in store.read(GENERATION_MANIFEST_PATH, GenerationManifest).records
    }
    book_dir = project_root / "books" / "tiny-latex"
    lexicon_path = book_dir / "lexicons" / "chatterbox-it.yaml"
    lexicon_path.parent.mkdir()
    lexicon_data = (
        "schema_version: pronunciation-lexicon/v1\n"
        "lexicon_id: chatterbox-it\n"
        "entries:\n"
        "  - entry_id: fondamenti\n"
        "    mode: literal\n"
        "    pattern: Fondamenti\n"
        "    spoken: Fondaménti\n"
    ).encode()
    lexicon_path.write_bytes(lexicon_data)
    config_path = book_dir / "book.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["normalization"]["lexicons"] = [
        {
            "path": "lexicons/chatterbox-it.yaml",
            "sha256": sha256_bytes(lexicon_data),
        }
    ]
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    for stage in ("normalize", "chunk"):
        result, _ = run("tiny-latex", stage)
        assert result.exit_code == 0, result.output
    synthesized, _ = run("tiny-latex", "synthesize")
    after = {
        record.chunk_id: record
        for record in store.read(GENERATION_MANIFEST_PATH, GenerationManifest).records
    }
    changed = [
        chunk_id
        for chunk_id, record in after.items()
        if record.cache_key != before[chunk_id].cache_key
    ]

    assert synthesized.exit_code == 0, synthesized.output
    assert json.loads(synthesized.stdout)["generated_count"] == 1
    assert changed == ["block-000002.s0000.p0000"]
    assert all(after[key] == before[key] for key in before if key not in changed)


def test_synthesis_cli_rejects_missing_chunk_manifest(run_book_fixture: object) -> None:
    run = _fixture_runner(run_book_fixture)
    for stage in ("ingest", "normalize"):
        prepared, _project_root = run("tiny-latex", stage)
        assert prepared.exit_code == 0, prepared.output
    result, _project_root = run("tiny-latex", "synthesize")

    assert result.exit_code == 1
    assert "chunk-manifest.json" in json.loads(result.stdout)["error"]


def _fixture_runner(value: object) -> FixtureRunner:
    assert callable(value)
    return cast(FixtureRunner, value)
