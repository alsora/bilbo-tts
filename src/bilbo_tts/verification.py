"""Round-trip ASR verification for generated book chunks."""

from __future__ import annotations

import math
import sys
import wave
from array import array
from collections import Counter
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Literal

from pydantic import Field

from bilbo_tts.artifacts import ArtifactError, ArtifactStore
from bilbo_tts.asr import MlxWhisperTranscriber, Transcriber
from bilbo_tts.chunk_service import CHUNK_MANIFEST_PATH
from bilbo_tts.config import VerificationConfig, VerificationThresholds
from bilbo_tts.models import (
    ChunkManifest,
    ChunkRecord,
    ContractModel,
    GenerationManifest,
    GenerationRecord,
    ManualReviewDecision,
    NonEmptyText,
    ReviewStatus,
    Sha256,
    VerificationHeuristics,
    VerificationManifest,
    VerificationRecord,
)
from bilbo_tts.qualification.asr_metrics import (
    align_words,
    character_error_rate,
    normalize_comparison_text,
    word_error_rate,
)
from bilbo_tts.qualification.audio import AudioValidationError, validate_wav_bytes
from bilbo_tts.qualification.candidates import (
    AsrCandidateConfig,
    CandidateConfigurationError,
    load_asr_candidate,
)
from bilbo_tts.serialization import canonical_sha256, sha256_bytes
from bilbo_tts.stages import load_stage_context
from bilbo_tts.synthesis import GENERATION_MANIFEST_PATH

VERIFICATION_MANIFEST_PATH = "manifests/verification-manifest.json"
VERIFICATION_REPORT_PATH = "reports/verification.md"
REPOSITORY_ROOT = Path(__file__).parents[2]
VERIFICATION_ALGORITHM_VERSION = "verification-v1"
_SILENCE_DBFS = -50.0


class VerificationError(ValueError):
    """Generated audio cannot be verified from its current artifacts."""


TranscriberFactory = Callable[[AsrCandidateConfig], Transcriber]


class VerifySummary(ContractModel):
    """Machine-readable result emitted by one verification pass."""

    schema_version: Literal["verify-summary/v1"] = "verify-summary/v1"
    status: Literal["completed", "retryable", "review"]
    book_id: NonEmptyText
    selected_count: int = Field(ge=0)
    transcribed_count: int = Field(ge=0)
    reused_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    retryable_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    verification_manifest_path: NonEmptyText
    verification_manifest_sha256: Sha256
    report_path: NonEmptyText
    report_sha256: Sha256


class ReviewDecisionSummary(ContractModel):
    """Machine-readable result of one explicit human review decision."""

    schema_version: Literal["review-decision-summary/v1"] = "review-decision-summary/v1"
    status: Literal["accepted", "retryable"]
    book_id: NonEmptyText
    chunk_id: NonEmptyText
    generation_sha256: Sha256
    verification_manifest_sha256: Sha256
    report_sha256: Sha256


def verify_book_pass(
    config_path: Path,
    project_root: Path,
    *,
    chapter: str | None = None,
    transcriber_factory: TranscriberFactory | None = None,
) -> VerifySummary:
    """Verify selected generated chunks once in the ASR process."""

    context = load_stage_context(config_path, project_root)
    store = context.workspace.artifacts
    chunks = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    chunk_reference = store.reference(CHUNK_MANIFEST_PATH)
    generations = store.read(GENERATION_MANIFEST_PATH, GenerationManifest)
    generation_reference = store.reference(GENERATION_MANIFEST_PATH)
    _validate_upstream(context.config.book_id, chunks, chunk_reference.sha256, generations)
    selected = _select_chunks(chunks, chapter)
    generation_by_chunk = {record.chunk_id: record for record in generations.records}
    missing = [chunk.chunk_id for chunk in selected if chunk.chunk_id not in generation_by_chunk]
    if missing:
        raise VerificationError(
            f"{len(missing)} selected chunk(s) lack valid generated audio; "
            f"run synthesize first: {', '.join(missing[:5])}"
        )

    asr_config = _load_book_asr_config(context.config.verification, context.workspace.project_root)
    verification_config_sha256 = canonical_sha256(
        {
            "algorithm_version": VERIFICATION_ALGORITHM_VERSION,
            "config": context.config.verification.model_dump(mode="json"),
        }
    )
    factory = transcriber_factory or _default_transcriber_factory
    transcriber: Transcriber | None = None
    records: list[VerificationRecord] = []
    transcribed_count = 0
    for chunk in selected:
        generation = generation_by_chunk[chunk.chunk_id]
        generation_sha256 = canonical_sha256(generation)
        attempt_path = _attempt_path(
            chunk.chunk_id,
            generation_sha256,
            verification_config_sha256,
        )
        cached = _read_cached_attempt(
            store,
            attempt_path,
            chunk,
            generation,
            generation_sha256,
        )
        if cached is not None:
            records.append(cached)
            continue
        if transcriber is None:
            transcriber = factory(asr_config)
        record = _verify_chunk(
            store,
            chunk,
            generation,
            generation_sha256,
            context.config.verification,
            transcriber,
        )
        sidecar_reference = store.reference(
            Path(generation.output_path).with_suffix(".json").as_posix()
        )
        store.write(attempt_path, record, dependencies=(sidecar_reference,))
        records.append(record)
        transcribed_count += 1

    manifest = VerificationManifest(
        book_id=chunks.book_id,
        generation_manifest_sha256=generation_reference.sha256,
        verification_config_sha256=verification_config_sha256,
        asr_model_id=asr_config.model_id,
        asr_model_revision=asr_config.revision,
        records=tuple(records),
    )
    manifest_reference = store.write(
        VERIFICATION_MANIFEST_PATH,
        manifest,
        dependencies=(chunk_reference, generation_reference),
    )
    report_reference = store.write_bytes(
        VERIFICATION_REPORT_PATH,
        render_verification_report(manifest, selected, generation_by_chunk).encode("utf-8"),
    )
    return _summary(
        manifest,
        manifest_reference.sha256,
        report_reference.sha256,
        transcribed_count=transcribed_count,
    )


def record_review_decision(
    config_path: Path,
    project_root: Path,
    *,
    chunk_id: str,
    action: Literal["accept", "regenerate"],
    reviewer: str,
    note: str,
) -> ReviewDecisionSummary:
    """Record a human decision that applies only to the current generated WAV."""

    context = load_stage_context(config_path, project_root)
    store = context.workspace.artifacts
    chunks = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    chunk_reference = store.reference(CHUNK_MANIFEST_PATH)
    generations = store.read(GENERATION_MANIFEST_PATH, GenerationManifest)
    generation_reference = store.reference(GENERATION_MANIFEST_PATH)
    manifest = store.read(VERIFICATION_MANIFEST_PATH, VerificationManifest)
    records = {record.chunk_id: record for record in manifest.records}
    try:
        current = records[chunk_id]
    except KeyError as error:
        raise VerificationError(f"chunk {chunk_id!r} is not in the current review queue") from error
    if current.status != ReviewStatus.REVIEW:
        raise VerificationError(
            f"chunk {chunk_id!r} has status {current.status.value!r}, not 'review'"
        )
    generation_by_chunk = {record.chunk_id: record for record in generations.records}
    generation = generation_by_chunk.get(chunk_id)
    if generation is None or canonical_sha256(generation) != current.generation_sha256:
        raise VerificationError(
            f"chunk {chunk_id!r} review does not match the current generated audio"
        )
    decision = ManualReviewDecision(action=action, reviewer=reviewer, note=note)
    status = ReviewStatus.ACCEPTED if action == "accept" else ReviewStatus.RETRYABLE
    updated = current.model_copy(
        update={
            "status": status,
            "reason_codes": (*current.reason_codes, f"manual-{action}"),
            "manual_decision": decision,
        }
    )
    updated = VerificationRecord.model_validate(updated.model_dump())
    attempt_path = _attempt_path(
        chunk_id,
        current.generation_sha256,
        manifest.verification_config_sha256,
    )
    sidecar_reference = store.reference(
        Path(generation.output_path).with_suffix(".json").as_posix()
    )
    store.write(attempt_path, updated, dependencies=(sidecar_reference,))
    records[chunk_id] = updated
    updated_manifest = manifest.model_copy(
        update={"records": tuple(records[record.chunk_id] for record in manifest.records)}
    )
    updated_manifest = VerificationManifest.model_validate(updated_manifest.model_dump())
    manifest_reference = store.write(
        VERIFICATION_MANIFEST_PATH,
        updated_manifest,
        dependencies=(chunk_reference, generation_reference),
    )
    selected = [chunk for chunk in chunks.chunks if chunk.chunk_id in records]
    report_reference = store.write_bytes(
        VERIFICATION_REPORT_PATH,
        render_verification_report(updated_manifest, selected, generation_by_chunk).encode("utf-8"),
    )
    return ReviewDecisionSummary(
        status="accepted" if action == "accept" else "retryable",
        book_id=manifest.book_id,
        chunk_id=chunk_id,
        generation_sha256=current.generation_sha256,
        verification_manifest_sha256=manifest_reference.sha256,
        report_sha256=report_reference.sha256,
    )


def render_verification_report(
    manifest: VerificationManifest,
    chunks: list[ChunkRecord],
    generation_by_chunk: dict[str, GenerationRecord],
) -> str:
    """Render complete current verification evidence and review actions."""

    records = {record.chunk_id: record for record in manifest.records}
    counts = Counter(record.status.value for record in manifest.records)
    lines = [
        f"# Verification report: {manifest.book_id}",
        "",
        f"- ASR model: `{manifest.asr_model_id}@{manifest.asr_model_revision}`.",
        f"- Accepted chunks: {counts[ReviewStatus.ACCEPTED.value]}.",
        f"- Retryable chunks: {counts[ReviewStatus.RETRYABLE.value]}.",
        f"- Chunks requiring review: {counts[ReviewStatus.REVIEW.value]}.",
        "",
    ]
    for chunk in chunks:
        record = records[chunk.chunk_id]
        generation = generation_by_chunk[chunk.chunk_id]
        lines.extend(
            [
                f"## `{chunk.chunk_id}` — `{record.status.value}`",
                "",
                f"- Source text: {chunk.display_text}",
                f"- Spoken text: {chunk.spoken_text}",
                f"- Transcript: {record.transcript or '[empty]'}",
                f"- Audio: `{generation.output_path}` (`{generation.output_sha256}`).",
                f"- Generation attempt: {record.attempt_number}.",
                f"- Duration: {record.duration_ms} ms.",
                f"- Speaking rate: {record.speaking_rate_wpm:.3f} WPM.",
                f"- WER: {record.wer:.6f}.",
                f"- CER: {record.cer:.6f}.",
                f"- Missing prefix words: {record.heuristics.missing_prefix_words}.",
                f"- Missing suffix words: {record.heuristics.missing_suffix_words}.",
                f"- Excess repeated n-grams: {record.heuristics.repeated_ngram_count}.",
                f"- Silence ratio: {record.heuristics.silence_ratio:.6f}.",
                f"- Clipped sample ratio: {record.heuristics.clipped_sample_ratio:.6f}.",
                f"- Peak: {record.heuristics.peak_dbfs:.3f} dBFS.",
                "- Reason codes: "
                + (
                    ", ".join(f"`{reason}`" for reason in record.reason_codes)
                    if record.reason_codes
                    else "none"
                )
                + ".",
                "",
                "Alignment:",
                "",
            ]
        )
        if record.alignment:
            lines.extend(
                f"- `{edit.operation}`: `{edit.expected}` -> `{edit.actual}`"
                for edit in record.alignment
            )
        else:
            lines.append("- No edits.")
        lines.extend(["", "Manual decision:", ""])
        if record.manual_decision is None:
            lines.append("- None.")
        else:
            lines.extend(
                [
                    f"- Action: `{record.manual_decision.action}`.",
                    f"- Reviewer: {record.manual_decision.reviewer}",
                    f"- Note: {record.manual_decision.note}",
                ]
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _verify_chunk(
    store: ArtifactStore,
    chunk: ChunkRecord,
    generation: GenerationRecord,
    generation_sha256: str,
    config: VerificationConfig,
    transcriber: Transcriber,
) -> VerificationRecord:
    try:
        wav_data = store.resolve(generation.output_path).read_bytes()
    except OSError as error:
        raise VerificationError(
            f"cannot read generated WAV for chunk {chunk.chunk_id!r}: {error}"
        ) from error
    if sha256_bytes(wav_data) != generation.output_sha256:
        raise VerificationError(
            f"generated WAV checksum does not match chunk {chunk.chunk_id!r} sidecar"
        )
    try:
        audio = validate_wav_bytes(
            wav_data,
            expected_sample_rate_hz=generation.sample_rate_hz,
        )
    except AudioValidationError as error:
        raise VerificationError(
            f"generated WAV for chunk {chunk.chunk_id!r} is invalid: {error}"
        ) from error
    heuristics = _audio_heuristics(wav_data)
    wav_path = store.resolve(generation.output_path)
    try:
        transcript = transcriber.transcribe(wav_path)
    except Exception as error:
        raise VerificationError(
            f"ASR transcription failed for chunk {chunk.chunk_id!r}: {str(error) or repr(error)}"
        ) from error
    normalized_reference = normalize_comparison_text(chunk.spoken_text)
    normalized_transcript = normalize_comparison_text(transcript)
    wer = word_error_rate(normalized_reference, normalized_transcript)
    cer = character_error_rate(normalized_reference, normalized_transcript)
    alignment = align_words(normalized_reference, normalized_transcript)
    duration_ms = max(1, round(audio.duration_seconds * 1000))
    speaking_rate = max(
        0.001,
        len(normalized_reference.split()) * 60 / audio.duration_seconds,
    )
    measured = heuristics.model_copy(
        update={
            "missing_prefix_words": alignment.missing_prefix_words,
            "missing_suffix_words": alignment.missing_suffix_words,
            "repeated_ngram_count": _repetition_excess(
                normalized_reference,
                normalized_transcript,
            ),
        }
    )
    measured = VerificationHeuristics.model_validate(measured.model_dump())
    reasons, status = _classify(
        transcript=normalized_transcript,
        wer=wer.rate,
        cer=cer.rate,
        speaking_rate=speaking_rate,
        heuristics=measured,
        thresholds=config.thresholds,
        attempt_number=generation.retry_number,
        max_auto_retries=config.max_auto_retries,
        word_count=len(normalized_reference.split()),
    )
    return VerificationRecord(
        chunk_id=chunk.chunk_id,
        generation_sha256=generation_sha256,
        attempt_number=generation.retry_number,
        transcript=transcript,
        wer=wer.rate,
        cer=cer.rate,
        alignment=alignment.edits,
        duration_ms=duration_ms,
        speaking_rate_wpm=speaking_rate,
        heuristics=measured,
        reason_codes=reasons,
        status=status,
    )


def _audio_heuristics(wav_data: bytes) -> VerificationHeuristics:
    try:
        with wave.open(BytesIO(wav_data), "rb") as wav:
            frames = wav.readframes(wav.getnframes())
    except (EOFError, wave.Error) as error:
        raise VerificationError(f"cannot inspect generated PCM samples: {error}") from error
    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise VerificationError("generated WAV contains no PCM samples")
    absolute = [abs(sample) for sample in samples]
    silence_limit = round(32767 * 10 ** (_SILENCE_DBFS / 20))
    silence_ratio = sum(value <= silence_limit for value in absolute) / len(absolute)
    clipped_ratio = sum(value >= 32760 for value in absolute) / len(absolute)
    peak = max(absolute)
    peak_dbfs = -120.0 if peak == 0 else min(0.0, max(-120.0, 20 * math.log10(peak / 32767)))
    return VerificationHeuristics(
        missing_prefix_words=0,
        missing_suffix_words=0,
        repeated_ngram_count=0,
        silence_ratio=silence_ratio,
        clipped_sample_ratio=clipped_ratio,
        peak_dbfs=peak_dbfs,
    )


def _repetition_excess(reference: str, transcript: str) -> int:
    reference_words = reference.split()
    transcript_words = transcript.split()
    reference_counts = _adjacent_repetitions(reference_words)
    transcript_counts = _adjacent_repetitions(transcript_words)
    return max(
        (count - reference_counts[ngram] for ngram, count in transcript_counts.items()),
        default=0,
    )


def _adjacent_repetitions(words: list[str]) -> Counter[tuple[str, ...]]:
    repetitions: Counter[tuple[str, ...]] = Counter()
    for size in range(1, 4):
        for index in range(len(words) - (2 * size) + 1):
            ngram = tuple(words[index : index + size])
            if ngram == tuple(words[index + size : index + (2 * size)]):
                repetitions[ngram] += 1
    return repetitions


def _classify(
    *,
    transcript: str,
    wer: float,
    cer: float,
    speaking_rate: float,
    heuristics: VerificationHeuristics,
    thresholds: VerificationThresholds,
    attempt_number: int,
    max_auto_retries: int,
    word_count: int,
) -> tuple[tuple[str, ...], ReviewStatus]:
    retry_reasons: list[str] = []
    if not transcript:
        retry_reasons.append("empty-transcript")
    if heuristics.missing_prefix_words > thresholds.max_missing_prefix_words:
        retry_reasons.append("missing-prefix")
    if heuristics.missing_suffix_words > thresholds.max_missing_suffix_words:
        retry_reasons.append("missing-suffix")
    if heuristics.repeated_ngram_count > thresholds.max_repeated_ngram_count:
        retry_reasons.append("repeated-ngram")
    if heuristics.silence_ratio > thresholds.max_silence_ratio:
        retry_reasons.append("excessive-silence")
    if heuristics.clipped_sample_ratio > thresholds.max_clipped_sample_ratio:
        retry_reasons.append("clipping")
    if word_count >= 4:
        if speaking_rate < thresholds.min_speaking_rate_wpm:
            retry_reasons.append("speaking-rate-low")
        if speaking_rate > thresholds.max_speaking_rate_wpm:
            retry_reasons.append("speaking-rate-high")
    review_reasons: list[str] = []
    if wer > thresholds.max_wer:
        review_reasons.append("wer-high")
    if cer > thresholds.max_cer:
        review_reasons.append("cer-high")
    reasons = tuple((*retry_reasons, *review_reasons))
    if retry_reasons:
        status = (
            ReviewStatus.RETRYABLE if attempt_number < max_auto_retries else ReviewStatus.REVIEW
        )
        return reasons, status
    if review_reasons:
        return reasons, ReviewStatus.REVIEW
    return reasons, ReviewStatus.ACCEPTED


def _read_cached_attempt(
    store: ArtifactStore,
    path: str,
    chunk: ChunkRecord,
    generation: GenerationRecord,
    generation_sha256: str,
) -> VerificationRecord | None:
    try:
        record = store.read(path, VerificationRecord)
    except ArtifactError:
        return None
    if (
        record.chunk_id != chunk.chunk_id
        or record.generation_sha256 != generation_sha256
        or record.attempt_number != generation.retry_number
    ):
        return None
    return record


def _validate_upstream(
    book_id: str,
    chunks: ChunkManifest,
    chunk_manifest_sha256: str,
    generations: GenerationManifest,
) -> None:
    if chunks.book_id != book_id or generations.book_id != book_id:
        raise VerificationError(
            f"verification artifacts do not belong to configured book {book_id!r}"
        )
    if generations.chunk_manifest_sha256 != chunk_manifest_sha256:
        raise VerificationError(
            "generation manifest does not reference the current chunk manifest; rerun synthesize"
        )


def _select_chunks(chunks: ChunkManifest, chapter: str | None) -> list[ChunkRecord]:
    if chapter is None:
        selected = list(chunks.chunks)
    else:
        selected = [chunk for chunk in chunks.chunks if chunk.chapter_id == chapter]
        if not selected:
            raise VerificationError(f"chapter {chapter!r} does not exist in the chunk manifest")
    if not selected:
        raise VerificationError("chunk manifest contains no chunks to verify")
    return selected


def _load_book_asr_config(
    config: VerificationConfig,
    _project_root: Path,
) -> AsrCandidateConfig:
    path = REPOSITORY_ROOT.joinpath(*Path(config.model_config_path).parts)
    try:
        return load_asr_candidate(path)
    except CandidateConfigurationError as error:
        raise VerificationError(str(error)) from error


def _attempt_path(chunk_id: str, generation_sha256: str, config_sha256: str) -> str:
    return f"verification/attempts/{chunk_id}/{generation_sha256}-{config_sha256}.json"


def _summary(
    manifest: VerificationManifest,
    manifest_sha256: str,
    report_sha256: str,
    *,
    transcribed_count: int,
) -> VerifySummary:
    accepted = sum(record.status == ReviewStatus.ACCEPTED for record in manifest.records)
    retryable = sum(record.status == ReviewStatus.RETRYABLE for record in manifest.records)
    review = sum(record.status == ReviewStatus.REVIEW for record in manifest.records)
    status: Literal["completed", "retryable", "review"] = (
        "retryable" if retryable else "review" if review else "completed"
    )
    return VerifySummary(
        status=status,
        book_id=manifest.book_id,
        selected_count=len(manifest.records),
        transcribed_count=transcribed_count,
        reused_count=len(manifest.records) - transcribed_count,
        accepted_count=accepted,
        retryable_count=retryable,
        review_count=review,
        verification_manifest_path=VERIFICATION_MANIFEST_PATH,
        verification_manifest_sha256=manifest_sha256,
        report_path=VERIFICATION_REPORT_PATH,
        report_sha256=report_sha256,
    )


def _default_transcriber_factory(config: AsrCandidateConfig) -> Transcriber:
    return MlxWhisperTranscriber(config)
