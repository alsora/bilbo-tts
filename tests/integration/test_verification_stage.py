from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from bilbo_tts.artifacts import ArtifactStore, StaleArtifactError
from bilbo_tts.chunk_service import CHUNK_MANIFEST_PATH
from bilbo_tts.models import ChunkManifest, GenerationManifest, ReviewStatus, VerificationManifest
from bilbo_tts.qualification.candidates import AsrCandidateConfig, LicenseMetadata
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


def test_scoped_pass_merges_only_still_current_records(
    run_book_fixture: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, project_root, store = _prepare_generated_fixture(run_book_fixture)
    chunks = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    chapter_ids = tuple(dict.fromkeys(chunk.chapter_id for chunk in chunks.chunks))
    assert len(chapter_ids) >= 2
    first_id, second_id = chapter_ids[:2]
    chunk_ids_by_chapter = {
        chapter_id: {chunk.chunk_id for chunk in chunks.chunks if chunk.chapter_id == chapter_id}
        for chapter_id in (first_id, second_id)
    }

    first = verify_book_pass(
        config_path,
        project_root,
        chapters=(first_id,),
        transcriber_factory=lambda _config: _Transcriber(_transcripts(store)),
    )
    second = verify_book_pass(
        config_path,
        project_root,
        chapters=(second_id,),
        transcriber_factory=lambda _config: _Transcriber(_transcripts(store)),
    )
    merged = store.read(VERIFICATION_MANIFEST_PATH, VerificationManifest)
    merged_ids = {record.chunk_id for record in merged.records}
    report = store.resolve("reports/verification.md").read_text(encoding="utf-8")

    assert first.selected_count == len(chunk_ids_by_chapter[first_id])
    assert second.selected_count == len(chunk_ids_by_chapter[second_id])
    assert second.accepted_count == second.selected_count
    assert merged_ids == chunk_ids_by_chapter[first_id] | chunk_ids_by_chapter[second_id]
    assert all(chunk_id in report for chunk_id in chunk_ids_by_chapter[second_id])
    assert all(chunk_id not in report for chunk_id in chunk_ids_by_chapter[first_id])

    generations = store.read(GENERATION_MANIFEST_PATH, GenerationManifest)
    stale_chunk_id = next(iter(chunk_ids_by_chapter[first_id]))
    updated_records = tuple(
        record.model_copy(update={"retry_number": record.retry_number + 1})
        if record.chunk_id == stale_chunk_id
        else record
        for record in generations.records
    )
    store.write(
        GENERATION_MANIFEST_PATH,
        generations.model_copy(update={"records": updated_records}),
        dependencies=(store.reference(CHUNK_MANIFEST_PATH),),
    )

    rerun = verify_book_pass(
        config_path,
        project_root,
        chapters=(second_id,),
        transcriber_factory=lambda _config: pytest.fail("selected records should be reused"),
    )
    current = store.read(VERIFICATION_MANIFEST_PATH, VerificationManifest)

    assert rerun.selected_count == len(chunk_ids_by_chapter[second_id])
    assert rerun.reused_count == rerun.selected_count
    assert stale_chunk_id not in {record.chunk_id for record in current.records}

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["verification"]["thresholds"]["max_wer"] = 0.44
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    config_changed = verify_book_pass(
        config_path,
        project_root,
        chapters=(second_id,),
        transcriber_factory=lambda _config: _Transcriber(_transcripts(store)),
    )
    after_config = store.read(VERIFICATION_MANIFEST_PATH, VerificationManifest)

    assert config_changed.transcribed_count == config_changed.selected_count
    assert {record.chunk_id for record in after_config.records} == chunk_ids_by_chapter[second_id]
    assert after_config.verification_config_sha256 != current.verification_config_sha256

    monkeypatch.setattr(
        "bilbo_tts.verification._load_book_asr_config",
        lambda _config, _root: AsrCandidateConfig(
            model_id=after_config.asr_model_id,
            revision="changed-revision",
            model_license=LicenseMetadata(
                spdx_identifier="MIT",
                source_url="https://github.com/openai/whisper/blob/main/LICENSE",
            ),
        ),
    )
    asr_changed = verify_book_pass(
        config_path,
        project_root,
        chapters=(second_id,),
        transcriber_factory=lambda _config: _Transcriber(_transcripts(store)),
    )
    after_asr = store.read(VERIFICATION_MANIFEST_PATH, VerificationManifest)

    assert asr_changed.transcribed_count == asr_changed.selected_count
    assert after_asr.asr_model_revision == "changed-revision"
    assert after_asr.verification_config_sha256 != after_config.verification_config_sha256


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


def test_human_can_regenerate_an_automatically_accepted_chunk(
    run_book_fixture: object,
) -> None:
    config_path, project_root, store = _prepare_generated_fixture(run_book_fixture)
    chunks = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    summary = verify_book_pass(
        config_path,
        project_root,
        transcriber_factory=lambda _config: _Transcriber(_transcripts(store)),
    )
    assert summary.status == "completed"
    chunk_id = chunks.chunks[0].chunk_id

    decision = record_review_decision(
        config_path,
        project_root,
        chunk_id=chunk_id,
        action="regenerate",
        reviewer="test-reviewer",
        note="Human listening found an artifact that ASR did not detect.",
    )

    assert decision.status == "retryable"
    current = store.read(VERIFICATION_MANIFEST_PATH, VerificationManifest)
    reviewed = next(record for record in current.records if record.chunk_id == chunk_id)
    assert reviewed.status == ReviewStatus.RETRYABLE
    assert reviewed.reason_codes == ("manual-regenerate",)
