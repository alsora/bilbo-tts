from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import pytest
import yaml

from bilbo_tts import synthesis
from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.config import SynthesisConfig, VoiceConfig
from bilbo_tts.models import (
    BreakKind,
    ChunkManifest,
    ChunkRecord,
    GenerationFailure,
    GenerationManifest,
    GenerationRecord,
    NormalizedBlock,
    NormalizedDocument,
    PauseMetadata,
    SynthesisIdentity,
    SynthesisSettings,
)
from bilbo_tts.qualification.candidates import TtsCandidateConfig
from bilbo_tts.synthesis import (
    GENERATION_MANIFEST_PATH,
    SynthesisError,
    synthesize_book,
)
from bilbo_tts.tts import (
    FakeTtsEngine,
    TtsCapabilities,
    TtsEngine,
    TtsHealth,
    TtsRequest,
    TtsResult,
)
from bilbo_tts.tts.factory import resolve_book_candidate


def make_project(
    tmp_path: Path,
    *,
    texts: tuple[str, ...] = ("Primo testo.", "Secondo testo."),
    max_retries: int = 2,
) -> tuple[Path, Path, ArtifactStore]:
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
                "metadata": {"title": "Libro", "author": "Autrice"},
                "normalization": {"version": "it-v1", "lexicons": []},
                "chunking": {"max_characters": 300},
                "synthesis": {
                    "engine": "fake",
                    "model_revision": "fake-v1",
                    "voice": {"voice_id": "fake-voice"},
                    "settings": {"sample_rate_hz": 24000, "seed": 7},
                    "max_retries": max_retries,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    store = ArtifactStore(root / "work" / "book")
    write_text_artifacts(store, texts)
    return root, config_path, store


def write_text_artifacts(store: ArtifactStore, texts: tuple[str, ...]) -> None:
    normalized = NormalizedDocument(
        book_id="book",
        book_document_sha256="a" * 64,
        normalization_version="it-v1",
        lexicon_sha256="b" * 64,
        blocks=tuple(
            NormalizedBlock(
                block_id=f"block-{index + 1}",
                display_text=text,
                spoken_text=text,
            )
            for index, text in enumerate(texts)
        ),
    )
    normalized_reference = store.write("manifests/normalized-document.json", normalized)
    chunks = ChunkManifest(
        book_id="book",
        normalized_document_sha256=normalized_reference.sha256,
        chunks=tuple(
            ChunkRecord.create(
                chunk_id=f"chunk-{index + 1}",
                chapter_id="chapter-1" if index < 2 else "chapter-2",
                paragraph_id=f"block-{index + 1}",
                sentence_id=f"sentence-{index + 1}",
                sequence=index,
                display_text=text,
                spoken_text=text,
                pause=PauseMetadata(
                    break_before=BreakKind.CHAPTER,
                    duration_ms=1500,
                ),
            )
            for index, text in enumerate(texts)
        ),
    )
    store.write(
        "manifests/chunk-manifest.json",
        chunks,
        dependencies=(normalized_reference,),
    )


def load_manifest(store: ArtifactStore) -> GenerationManifest:
    return store.read(GENERATION_MANIFEST_PATH, GenerationManifest)


def fake_factory(
    candidate: TtsCandidateConfig,
    _root: Path,
) -> TtsEngine:
    return FakeTtsEngine(
        model=candidate.model,
        sample_rate_hz=candidate.settings.sample_rate_hz,
        voice_id=candidate.voice.voice_id,
    )


def test_synthesis_is_resumable_and_second_run_does_not_construct_engine(
    tmp_path: Path,
) -> None:
    root, config, store = make_project(tmp_path)
    first = synthesize_book(config, root, engine_factory=fake_factory)
    manifest_bytes = store.resolve(GENERATION_MANIFEST_PATH).read_bytes()
    wav_bytes = {
        record.chunk_id: store.resolve(record.output_path).read_bytes()
        for record in load_manifest(store).records
    }

    def unexpected_factory(_candidate: TtsCandidateConfig, _root: Path) -> TtsEngine:
        raise AssertionError("no-op synthesis must not construct an engine")

    second = synthesize_book(config, root, engine_factory=unexpected_factory)

    assert first.generated_count == 2
    assert second.generated_count == 0
    assert second.skipped_count == 2
    assert store.resolve(GENERATION_MANIFEST_PATH).read_bytes() == manifest_bytes
    assert {
        record.chunk_id: store.resolve(record.output_path).read_bytes()
        for record in load_manifest(store).records
    } == wav_bytes


def test_interruption_retains_completed_chunks_and_resume_generates_only_missing(
    tmp_path: Path,
) -> None:
    root, config, store = make_project(tmp_path, texts=("Uno.", "Due.", "Tre."))
    delegate = fake_factory
    calls = 0

    class InterruptingEngine:
        def __init__(self, engine: TtsEngine) -> None:
            self.engine = engine

        @property
        def capabilities(self) -> TtsCapabilities:
            return self.engine.capabilities

        def health(self) -> TtsHealth:
            return self.engine.health()

        def synthesize(self, request: TtsRequest) -> TtsResult:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt("simulated interruption")
            return self.engine.synthesize(request)

    def interrupting_factory(candidate: TtsCandidateConfig, path: Path) -> TtsEngine:
        return InterruptingEngine(delegate(candidate, path))

    with pytest.raises(KeyboardInterrupt, match="simulated"):
        synthesize_book(config, root, engine_factory=interrupting_factory)

    sidecars = list(store.root.glob("audio/*/*.json"))
    assert len(sidecars) == 1
    first_sidecar_bytes = sidecars[0].read_bytes()

    resumed = synthesize_book(config, root, engine_factory=fake_factory)

    assert resumed.generated_count == 2
    assert resumed.skipped_count == 1
    assert sidecars[0].read_bytes() == first_sidecar_bytes
    assert len(load_manifest(store).records) == 3


class FailingEngine:
    def __init__(self, delegate: TtsEngine, failing_text: str) -> None:
        self.delegate = delegate
        self.failing_text = failing_text
        self.calls: list[str] = []

    @property
    def capabilities(self) -> TtsCapabilities:
        return self.delegate.capabilities

    def health(self) -> TtsHealth:
        return self.delegate.health()

    def synthesize(self, request: TtsRequest) -> TtsResult:
        self.calls.append(request.spoken_text)
        if request.spoken_text == self.failing_text:
            raise RuntimeError("simulated generation failure")
        return self.delegate.synthesize(request)


def test_failures_are_bounded_persisted_and_failed_only_recovers(tmp_path: Path) -> None:
    root, config, store = make_project(tmp_path, max_retries=2)
    engine: FailingEngine | None = None

    def failing_factory(candidate: TtsCandidateConfig, path: Path) -> TtsEngine:
        nonlocal engine
        engine = FailingEngine(fake_factory(candidate, path), "Secondo testo.")
        return engine

    first = synthesize_book(config, root, engine_factory=failing_factory)
    manifest = load_manifest(store)

    assert first.status == "partial"
    assert first.failed_count == 1
    assert engine is not None
    assert engine.calls.count("Secondo testo.") == 3
    assert len(manifest.records) == 1
    assert manifest.failures[0].attempt_count == 3
    assert "simulated generation failure" in manifest.failures[0].message

    recovered = synthesize_book(
        config,
        root,
        failed_only=True,
        engine_factory=fake_factory,
    )

    assert recovered.selected_count == 1
    assert recovered.generated_count == 1
    assert len(load_manifest(store).records) == 2
    assert load_manifest(store).failures == ()


def test_each_chunk_state_is_validated_once_per_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config, store = make_project(tmp_path, texts=("Uno.", "Due.", "Tre."))
    reads: list[str] = []
    original = synthesis._read_current_state

    def counting(
        store: ArtifactStore,
        chunk: ChunkRecord,
        identity: SynthesisIdentity,
    ) -> tuple[GenerationRecord | None, GenerationFailure | None]:
        reads.append(chunk.chunk_id)
        return original(store, chunk, identity)

    monkeypatch.setattr(synthesis, "_read_current_state", counting)
    summary = synthesize_book(config, root, engine_factory=fake_factory)

    assert summary.generated_count == 3
    assert sorted(reads) == ["chunk-1", "chunk-2", "chunk-3"]
    assert len(load_manifest(store).records) == 3


def test_retries_vary_the_seed_and_recover_deterministic_failures(tmp_path: Path) -> None:
    root, config, store = make_project(tmp_path, texts=("Testo.",), max_retries=2)
    attempt_seeds: list[int] = []

    class SeedSensitiveEngine:
        def __init__(self, delegate: TtsEngine, failing_seed: int) -> None:
            self.delegate = delegate
            self.failing_seed = failing_seed

        @property
        def capabilities(self) -> TtsCapabilities:
            return self.delegate.capabilities

        def health(self) -> TtsHealth:
            return self.delegate.health()

        def synthesize(self, request: TtsRequest) -> TtsResult:
            attempt_seeds.append(request.settings.seed)
            if request.settings.seed == self.failing_seed:
                raise RuntimeError("deterministic failure for this seed")
            return self.delegate.synthesize(request)

    def seed_sensitive_factory(candidate: TtsCandidateConfig, path: Path) -> TtsEngine:
        return SeedSensitiveEngine(fake_factory(candidate, path), failing_seed=7)

    summary = synthesize_book(config, root, engine_factory=seed_sensitive_factory)
    record = load_manifest(store).records[0]

    assert attempt_seeds == [7, 8]
    assert summary.generated_count == 1
    assert summary.failed_count == 0
    assert record.retry_number == 1
    assert record.identity.settings.seed == 7


def test_chapter_range_and_force_filters_intersect(tmp_path: Path) -> None:
    root, config, store = make_project(
        tmp_path,
        texts=("Uno.", "Due.", "Tre.", "Quattro."),
    )
    first = synthesize_book(
        config,
        root,
        chapter="chapter-1",
        chunk_start=1,
        chunk_end=1,
        engine_factory=fake_factory,
    )
    forced = synthesize_book(
        config,
        root,
        chapter="chapter-1",
        chunk_start=1,
        chunk_end=1,
        force=True,
        engine_factory=fake_factory,
    )

    assert first.selected_count == first.generated_count == 1
    assert forced.selected_count == forced.generated_count == 1
    assert len(load_manifest(store).records) == 1
    assert set(load_manifest(store).missing_chunk_ids) == {"chunk-1", "chunk-3", "chunk-4"}


@pytest.mark.parametrize(
    "chapter,chunk_start,chunk_end,match",
    [
        ("missing", None, None, "does not exist"),
        (None, -1, None, "zero or greater"),
        (None, 1, 0, "must not exceed"),
        (None, None, 99, "exceeds maximum"),
    ],
)
def test_invalid_selectors_fail_before_engine_construction(
    tmp_path: Path,
    chapter: str | None,
    chunk_start: int | None,
    chunk_end: int | None,
    match: str,
) -> None:
    root, config, _store = make_project(tmp_path)

    def unexpected_factory(_candidate: TtsCandidateConfig, _root: Path) -> TtsEngine:
        raise AssertionError("selector validation must precede engine construction")

    with pytest.raises(SynthesisError, match=match):
        synthesize_book(
            config,
            root,
            engine_factory=unexpected_factory,
            chapter=chapter,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
        )


def test_duplicate_spoken_text_still_has_one_wav_per_chunk(tmp_path: Path) -> None:
    root, config, store = make_project(tmp_path, texts=("Uguale.", "Uguale."))
    synthesize_book(config, root, engine_factory=fake_factory)
    records = load_manifest(store).records

    assert records[0].cache_key == records[1].cache_key
    assert records[0].output_path != records[1].output_path
    assert all(store.resolve(record.output_path).is_file() for record in records)


def test_changed_spoken_text_invalidates_only_the_affected_chunk(tmp_path: Path) -> None:
    root, config, store = make_project(tmp_path)
    synthesize_book(config, root, engine_factory=fake_factory)
    before = {record.chunk_id: record for record in load_manifest(store).records}

    write_text_artifacts(store, ("Primo testo.", "Secondo testo corretto."))
    rerun = synthesize_book(config, root, engine_factory=fake_factory)
    after = {record.chunk_id: record for record in load_manifest(store).records}

    assert rerun.generated_count == 1
    assert rerun.skipped_count == 1
    assert after["chunk-1"] == before["chunk-1"]
    assert after["chunk-2"].cache_key != before["chunk-2"].cache_key


def wav_bytes(
    *,
    channels: int = 1,
    width: int = 2,
    rate: int = 24_000,
    frames: bytes = b"\0\0",
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(frames)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "corruption",
    [
        "missing-wav",
        "missing-sidecar",
        "malformed-sidecar",
        "empty",
        "truncated",
        "wrong-channels",
        "wrong-width",
        "wrong-rate",
        "checksum",
        "metadata",
    ],
)
def test_invalid_existing_pairs_are_regenerated(
    tmp_path: Path,
    corruption: str,
) -> None:
    root, config, store = make_project(tmp_path, texts=("Testo.",))
    synthesize_book(config, root, engine_factory=fake_factory)
    record = load_manifest(store).records[0]
    wav_path = store.resolve(record.output_path)
    sidecar_path = wav_path.with_suffix(".json")

    if corruption == "missing-wav":
        wav_path.unlink()
    elif corruption == "missing-sidecar":
        sidecar_path.unlink()
    elif corruption == "malformed-sidecar":
        sidecar_path.write_text("{broken", encoding="utf-8")
    elif corruption == "empty":
        wav_path.write_bytes(b"")
    elif corruption == "truncated":
        wav_path.write_bytes(wav_bytes(frames=b"\0" * 8)[:-2])
    elif corruption == "wrong-channels":
        wav_path.write_bytes(wav_bytes(channels=2, frames=b"\0" * 8))
    elif corruption == "wrong-width":
        wav_path.write_bytes(wav_bytes(width=1, frames=b"\0" * 4))
    elif corruption == "wrong-rate":
        wav_path.write_bytes(wav_bytes(rate=48_000))
    elif corruption == "checksum":
        wav_path.write_bytes(wav_path.read_bytes() + b"x")
    elif corruption == "metadata":
        payload = record.model_dump(mode="json")
        payload["frame_count"] = record.frame_count + 24
        payload["duration_ms"] = record.duration_ms + 1
        store.write(
            sidecar_path.relative_to(store.root).as_posix(),
            GenerationRecord.model_validate(payload),
        )
    else:
        raise AssertionError(corruption)

    repaired = synthesize_book(config, root, engine_factory=fake_factory)

    assert repaired.generated_count == 1
    assert len(load_manifest(store).records) == 1


def test_wrong_model_revision_is_rejected(tmp_path: Path) -> None:
    root, config, _store = make_project(tmp_path)
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    payload["synthesis"]["model_revision"] = "mutable-main"
    config.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match the pinned"):
        synthesize_book(config, root, engine_factory=fake_factory)


def test_book_candidate_resolution_is_independent_of_private_project_root(
    tmp_path: Path,
) -> None:
    synthesis = SynthesisConfig(
        engine="chatterbox",
        model_revision="5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18",
        voice=VoiceConfig(voice_id="builtin"),
        settings=SynthesisSettings(
            sample_rate_hz=24_000,
            seed=20_260_711,
            temperature=0.8,
        ),
    )

    candidate = resolve_book_candidate(synthesis, tmp_path / "private-project")

    assert candidate.engine == "chatterbox"
    assert candidate.model.revision == synthesis.model_revision


def test_report_is_compact_and_canonical(tmp_path: Path) -> None:
    root, config, store = make_project(tmp_path)
    synthesize_book(config, root, engine_factory=fake_factory)

    report = store.resolve("reports/synthesis.md").read_text(encoding="utf-8")
    raw_manifest = json.loads(store.resolve(GENERATION_MANIFEST_PATH).read_bytes())

    assert "- Valid WAVs: 2" in report
    assert "chunk-1" not in report
    assert raw_manifest["artifact_type"] == "generation-manifest"
