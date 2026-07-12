from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import pytest

from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.assembly import (
    AssemblyError,
    _encode_command,
    _escape_metadata,
    _measurement,
    _parse_loudnorm_json,
    _select_chunks,
    _validate_inputs,
    _validate_media,
    _write_pcm_timeline,
    assemble_book,
)
from bilbo_tts.models import (
    BackendIdentity,
    BookDocument,
    BreakKind,
    ChapterDocument,
    ChapterMarker,
    ChunkManifest,
    ChunkRecord,
    GenerationManifest,
    GenerationRecord,
    LoudnessMeasurement,
    ModelIdentity,
    PauseMetadata,
    ProbedMedia,
    ReviewStatus,
    SourceFormat,
    SynthesisIdentity,
    SynthesisSettings,
    VerificationHeuristics,
    VerificationManifest,
    VerificationRecord,
    VoiceIdentity,
)
from bilbo_tts.serialization import canonical_sha256, sha256_bytes

HASH = "a" * 64
SAMPLE_RATE = 8_000


def test_override_flag_and_note_are_required_together(tmp_path: Path) -> None:
    with pytest.raises(AssemblyError, match="required together"):
        assemble_book(
            Path("books/book/book.yaml"),
            tmp_path,
            allow_unaccepted=True,
        )
    with pytest.raises(AssemblyError, match="required together"):
        assemble_book(
            Path("books/book/book.yaml"),
            tmp_path,
            override_note="note without flag",
        )


def _artifacts(
    tmp_path: Path,
    *,
    status: ReviewStatus = ReviewStatus.ACCEPTED,
    verification_sha256: str | None = None,
) -> tuple[
    ArtifactStore,
    BookDocument,
    ChunkManifest,
    GenerationManifest,
    VerificationManifest,
]:
    store = ArtifactStore(tmp_path / "work" / "book")
    chunks = (
        ChunkRecord.create(
            chunk_id="chunk-1",
            chapter_id="chapter-1",
            paragraph_id="paragraph-1",
            sentence_id="sentence-1",
            sequence=0,
            display_text="Uno.",
            spoken_text="Uno.",
            pause=PauseMetadata(break_before=BreakKind.CHAPTER, duration_ms=100),
        ),
        ChunkRecord.create(
            chunk_id="chunk-2",
            chapter_id="chapter-2",
            paragraph_id="paragraph-2",
            sentence_id="sentence-2",
            sequence=1,
            display_text="Due.",
            spoken_text="Due.",
            pause=PauseMetadata(break_before=BreakKind.CHAPTER, duration_ms=200),
        ),
    )
    chunk_manifest = ChunkManifest(
        book_id="book",
        normalized_document_sha256=HASH,
        chunks=chunks,
    )
    document = BookDocument(
        book_id="book",
        source_format=SourceFormat.LATEX,
        source_sha256=HASH,
        chapters=(
            ChapterDocument(chapter_id="chapter-1", order=0, title="Uno", blocks=()),
            ChapterDocument(chapter_id="chapter-2", order=1, title="Due", blocks=()),
        ),
    )
    identity = SynthesisIdentity(
        spoken_text="Uno.",
        normalization_version="it-v1",
        model=ModelIdentity(engine="fake", revision="test"),
        backend=BackendIdentity(backend="stdlib", model_id="test/fake"),
        voice=VoiceIdentity(voice_id="test"),
        settings=SynthesisSettings(sample_rate_hz=SAMPLE_RATE, seed=1),
    )
    records = []
    for chunk in chunks:
        path = f"audio/{chunk.chunk_id}/audio.wav"
        wav_path = store.resolve(path)
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(wav_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(b"\x01\x00" * 800)
        data = wav_path.read_bytes()
        chunk_identity = identity.model_copy(update={"spoken_text": chunk.spoken_text})
        records.append(
            GenerationRecord(
                chunk_id=chunk.chunk_id,
                chunk_content_sha256=chunk.content_sha256,
                identity=chunk_identity,
                cache_key=chunk_identity.cache_key(),
                output_path=path,
                output_sha256=sha256_bytes(data),
                sample_rate_hz=SAMPLE_RATE,
                frame_count=800,
                duration_ms=100,
                retry_number=0,
            )
        )
    generation_manifest = GenerationManifest(
        book_id="book",
        chunk_manifest_sha256=HASH,
        records=tuple(records),
    )
    verification_manifest = VerificationManifest(
        book_id="book",
        generation_manifest_sha256=HASH,
        verification_config_sha256=HASH,
        asr_model_id="test/whisper",
        asr_model_revision="test",
        records=tuple(
            VerificationRecord(
                chunk_id=record.chunk_id,
                generation_sha256=(
                    verification_sha256
                    if verification_sha256 is not None and index == 0
                    else canonical_sha256(record)
                ),
                attempt_number=0,
                transcript=chunks[index].spoken_text,
                wer=0,
                cer=0,
                duration_ms=100,
                speaking_rate_wpm=100,
                heuristics=VerificationHeuristics(
                    missing_prefix_words=0,
                    missing_suffix_words=0,
                    repeated_ngram_count=0,
                    silence_ratio=0,
                    clipped_sample_ratio=0,
                    peak_dbfs=-20,
                ),
                status=status,
            )
            for index, record in enumerate(records)
        ),
    )
    return store, document, chunk_manifest, generation_manifest, verification_manifest


def test_input_validation_requires_current_accepted_audio(tmp_path: Path) -> None:
    store, _document, chunks, generations, verification = _artifacts(tmp_path)

    records, sample_rate, unaccepted = _validate_inputs(
        store,
        chunks.chunks,
        generations,
        verification,
        allow_unaccepted=False,
    )

    assert list(records) == ["chunk-1", "chunk-2"]
    assert sample_rate == SAMPLE_RATE
    assert unaccepted == []


@pytest.mark.parametrize("status", [ReviewStatus.REVIEW, ReviewStatus.RETRYABLE])
def test_unaccepted_audio_requires_override_and_stale_verification_always_blocks(
    tmp_path: Path,
    status: ReviewStatus,
) -> None:
    store, _document, chunks, generations, review = _artifacts(
        tmp_path,
        status=status,
    )
    with pytest.raises(AssemblyError, match="not accepted"):
        _validate_inputs(
            store,
            chunks.chunks,
            generations,
            review,
            allow_unaccepted=False,
        )
    _, _, unaccepted = _validate_inputs(
        store,
        chunks.chunks,
        generations,
        review,
        allow_unaccepted=True,
    )
    assert unaccepted == ["chunk-1", "chunk-2"]

    stale = _artifacts(tmp_path / "stale", verification_sha256="b" * 64)[-1]
    stale_store, _, stale_chunks, stale_generations, _ = _artifacts(tmp_path / "stale-current")
    with pytest.raises(AssemblyError, match="verification is stale"):
        _validate_inputs(
            stale_store,
            stale_chunks.chunks,
            stale_generations,
            stale,
            allow_unaccepted=True,
        )


def test_missing_verification_can_be_overridden_but_missing_or_corrupt_audio_cannot(
    tmp_path: Path,
) -> None:
    store, _document, chunks, generations, verification = _artifacts(tmp_path)
    unverified = verification.model_copy(update={"records": ()})
    with pytest.raises(AssemblyError, match="not accepted"):
        _validate_inputs(
            store,
            chunks.chunks,
            generations,
            unverified,
            allow_unaccepted=False,
        )
    _, _, unaccepted = _validate_inputs(
        store,
        chunks.chunks,
        generations,
        unverified,
        allow_unaccepted=True,
    )
    assert unaccepted == ["chunk-1", "chunk-2"]

    missing = generations.model_copy(update={"records": generations.records[1:]})
    with pytest.raises(AssemblyError, match="lacks valid generated audio"):
        _validate_inputs(
            store,
            chunks.chunks,
            missing,
            verification,
            allow_unaccepted=True,
        )

    store.resolve(generations.records[0].output_path).write_bytes(b"not a WAV")
    with pytest.raises(AssemblyError, match="WAV is invalid"):
        _validate_inputs(
            store,
            chunks.chunks,
            generations,
            verification,
            allow_unaccepted=True,
        )


def test_pcm_timeline_preserves_order_pauses_and_chapter_boundaries(tmp_path: Path) -> None:
    store, document, chunks, generations, _verification = _artifacts(tmp_path)
    output = tmp_path / "timeline.wav"

    inputs, chapters, total_frames = _write_pcm_timeline(
        output,
        store,
        chunks.chunks,
        {record.chunk_id: record for record in generations.records},
        document,
        SAMPLE_RATE,
    )

    assert [record.chunk_id for record in inputs] == ["chunk-1", "chunk-2"]
    assert [record.pause_frame_count for record in inputs] == [800, 1600]
    assert [record.start_frame for record in inputs] == [0, 1600]
    assert chapters == (
        ChapterMarker(chapter_id="chapter-1", title="Uno", start_frame=0, end_frame=1600),
        ChapterMarker(chapter_id="chapter-2", title="Due", start_frame=1600, end_frame=4000),
    )
    assert total_frames == 4000
    with wave.open(str(output), "rb") as timeline:
        assert timeline.getnframes() == 4000


def test_selection_and_metadata_escaping_are_strict(tmp_path: Path) -> None:
    chunks = _artifacts(tmp_path)[2]

    assert [chunk.chunk_id for chunk in _select_chunks(chunks, "chapter-2")] == ["chunk-2"]
    with pytest.raises(AssemblyError, match="does not exist"):
        _select_chunks(chunks, "missing")
    assert _escape_metadata(r"A=B; C#D\E") == r"A\=B\; C\#D\\E"


def test_loudnorm_json_parsing_and_measurement() -> None:
    stderr = """
    noise
    {
      "input_i" : "-20.10",
      "input_tp" : "-3.00",
      "input_lra" : "1.20",
      "input_thresh" : "-30.00",
      "output_i" : "-18.00",
      "output_tp" : "-2.00",
      "output_lra" : "1.10",
      "output_thresh" : "-28.00",
      "target_offset" : "0.00"
    }
    """
    values = _parse_loudnorm_json(stderr)

    measurement = _measurement(values, "output", "input")

    assert measurement.integrated_lufs == -20.1
    assert measurement.true_peak_db == -3
    with pytest.raises(AssemblyError, match="did not emit"):
        _parse_loudnorm_json("no JSON")


def test_encode_command_pins_output_to_the_pcm_sample_rate(tmp_path: Path) -> None:
    measured = {
        "input_i": "-20",
        "input_tp": "-3",
        "input_lra": "1",
        "input_thresh": "-30",
        "target_offset": "0",
    }

    command = _encode_command(
        "ffmpeg",
        tmp_path / "input.wav",
        tmp_path / "chapters.ffmeta",
        tmp_path / "output.m4b",
        None,
        -18,
        -2,
        64,
        24_000,
        measured,
    )

    assert command[command.index("-ar") + 1] == "24000"


def test_media_validation_checks_duration_chapters_metadata_and_loudness() -> None:
    media = ProbedMedia(
        codec_name="aac",
        channels=1,
        sample_rate_hz=SAMPLE_RATE,
        duration_ms=500,
        tags={"title": "Libro", "artist": "Autrice"},
        cover_art=False,
        chapter_count=1,
    )
    chapters = (ChapterMarker(chapter_id="chapter-1", title="Uno", start_frame=0, end_frame=4000),)
    loudness = LoudnessMeasurement(
        phase="output",
        integrated_lufs=-18.1,
        true_peak_db=-2.1,
        loudness_range_lu=1,
        threshold_lufs=-28,
        target_offset_lu=0,
    )

    _validate_media(
        media,
        [(0, 500)],
        chapters,
        4000,
        SAMPLE_RATE,
        "Libro",
        "Autrice",
        False,
        loudness,
        -18,
        -2,
        0.5,
        0.2,
    )

    with pytest.raises(AssemblyError, match="outside"):
        _validate_media(
            media,
            [(0, 500)],
            chapters,
            4000,
            SAMPLE_RATE,
            "Libro",
            "Autrice",
            False,
            loudness.model_copy(update={"integrated_lufs": -19.0}),
            -18,
            -2,
            0.5,
            0.2,
        )


def test_command_runner_result_type_is_text() -> None:
    result = subprocess.CompletedProcess(["ffmpeg"], 0, stdout="ok", stderr="")
    assert result.stdout == "ok"
