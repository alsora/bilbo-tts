from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from bilbo_tts.artifacts import ArtifactStore, StaleArtifactError
from bilbo_tts.chunk_service import CHUNK_MANIFEST_PATH
from bilbo_tts.models import ChunkManifest, GenerationManifest, ReviewStatus, VerificationManifest
from bilbo_tts.synthesis import GENERATION_MANIFEST_PATH, synthesize_book
from bilbo_tts.verification import (
    VERIFICATION_MANIFEST_PATH,
    record_review_decision,
    verify_book_pass,
)

FixtureRunner = Callable[[str, str], tuple[Any, Path]]


class _Transcriber:
    def __init__(self, transcripts: dict[str, str]) -> None:
        self.transcripts = transcripts
        self.calls: list[Path] = []

    def transcribe(self, wav_path: Path) -> str:
        self.calls.append(wav_path)
        return self.transcripts[wav_path.name]


def _prepare_generated_fixture(run_book_fixture: object) -> tuple[Path, Path, ArtifactStore]:
    run = cast(FixtureRunner, run_book_fixture)
    for stage in ("ingest", "normalize", "chunk", "synthesize"):
        result, project_root = run("tiny-latex", stage)
        assert result.exit_code == 0, result.output
    config_path = project_root / "books" / "tiny-latex" / "book.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["verification"]["thresholds"] = {
        "max_wer": 0.45,
        "max_cer": 0.30,
        "max_missing_prefix_words": 1,
        "max_missing_suffix_words": 1,
        "max_repeated_ngram_count": 0,
        "max_silence_ratio": 0.95,
        "max_clipped_sample_ratio": 0.001,
        "min_speaking_rate_wpm": 1,
        "max_speaking_rate_wpm": 2_000,
    }
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    asr_path = project_root / "config" / "qualification" / "asr.yaml"
    asr_path.parent.mkdir(parents=True)
    asr_path.write_text(
        "\n".join(
            [
                "schema_version: asr-candidate/v1",
                "engine: mlx-whisper",
                "backend: mlx",
                "model_id: test/whisper",
                "revision: test-revision",
                "language: it",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path, project_root, ArtifactStore(project_root / "work" / "tiny-latex")


def _transcripts(store: ArtifactStore) -> dict[str, str]:
    chunks = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    generations = store.read(GENERATION_MANIFEST_PATH, GenerationManifest)
    spoken = {chunk.chunk_id: chunk.spoken_text for chunk in chunks.chunks}
    return {
        Path(record.output_path).name: spoken[record.chunk_id] for record in generations.records
    }


def test_verification_pass_is_complete_and_noop_on_rerun(run_book_fixture: object) -> None:
    config_path, project_root, store = _prepare_generated_fixture(run_book_fixture)
    transcriber = _Transcriber(_transcripts(store))

    first = verify_book_pass(
        config_path,
        project_root,
        transcriber_factory=lambda _config: transcriber,
    )
    manifest_bytes = store.resolve(VERIFICATION_MANIFEST_PATH).read_bytes()
    second = verify_book_pass(
        config_path,
        project_root,
        transcriber_factory=lambda _config: pytest.fail("cached pass loaded ASR"),
    )

    assert first.status == "completed"
    assert first.transcribed_count == first.selected_count
    assert len(transcriber.calls) == first.selected_count
    assert second.status == "completed"
    assert second.transcribed_count == 0
    assert second.reused_count == second.selected_count
    assert store.resolve(VERIFICATION_MANIFEST_PATH).read_bytes() == manifest_bytes


def test_manual_decision_is_bound_to_generation_and_retry_becomes_stale(
    run_book_fixture: object,
) -> None:
    config_path, project_root, store = _prepare_generated_fixture(run_book_fixture)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["verification"]["max_auto_retries"] = 0
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    chunks = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    bad_transcripts = {name: "testo completamente diverso" for name in _transcripts(store)}
    summary = verify_book_pass(
        config_path,
        project_root,
        transcriber_factory=lambda _config: _Transcriber(bad_transcripts),
    )
    assert summary.status == "review"
    chunk_id = chunks.chunks[0].chunk_id

    decision = record_review_decision(
        config_path,
        project_root,
        chunk_id=chunk_id,
        action="regenerate",
        reviewer="test-reviewer",
        note="The generated audio does not match the source.",
    )
    assert decision.status == "retryable"
    current = store.read(VERIFICATION_MANIFEST_PATH, VerificationManifest)
    reviewed = next(record for record in current.records if record.chunk_id == chunk_id)
    assert reviewed.status == ReviewStatus.RETRYABLE
    assert reviewed.manual_decision is not None

    retry = synthesize_book(
        config_path,
        project_root,
        verification_retry=True,
    )

    assert retry.generated_count == 1
    generations = store.read(GENERATION_MANIFEST_PATH, GenerationManifest)
    regenerated = next(record for record in generations.records if record.chunk_id == chunk_id)
    assert regenerated.retry_number == 1
    with pytest.raises(StaleArtifactError):
        store.read(VERIFICATION_MANIFEST_PATH, VerificationManifest)
