"""Minimal separate-process MLX-Whisper qualification scoring."""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Literal, NamedTuple, Self, cast

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.models import ContractModel, Identifier, NonEmptyText, Sha256
from bilbo_tts.qualification.asr_metrics import (
    EditMetric,
    character_error_rate,
    normalize_comparison_text,
    word_error_rate,
)
from bilbo_tts.qualification.audio import AudioValidationError, validate_wav_bytes
from bilbo_tts.qualification.candidates import (
    AsrCandidateConfig,
    candidate_path,
    load_asr_candidate,
)
from bilbo_tts.qualification.corpus import (
    CorpusCategory,
    CorpusExcerpt,
    QualificationCorpus,
    default_corpus_path,
    load_corpus,
)
from bilbo_tts.qualification.results import (
    QualificationError,
    QualificationResult,
    QualificationSample,
    load_qualification_result,
)
from bilbo_tts.serialization import canonical_json_bytes, canonical_sha256, sha256_bytes

MODEL_ID = "mlx-community/whisper-large-v3-turbo"
MODEL_REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"
RESULT_PATH = "result.json"
REPORT_PATH = "summary.md"


class AsrSettings(ContractModel):
    """Exact immutable MLX-Whisper transcription settings."""

    language: Literal["it"] = "it"
    task: Literal["transcribe"] = "transcribe"
    temperature: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    fp16: Literal[True] = True
    verbose: None = None
    word_timestamps: Literal[False] = False

    @model_validator(mode="after")
    def temperature_is_deterministic(self) -> Self:
        if self.temperature != 0.0:
            raise ValueError("ASR qualification temperature must be exactly 0.0")
        return self


class AsrFailure(ContractModel):
    """One actionable transcription failure."""

    exception_type: NonEmptyText
    message: NonEmptyText


class AsrQualificationSample(ContractModel):
    """Raw evidence and normalized metrics for one qualification excerpt."""

    excerpt_id: Identifier
    categories: tuple[CorpusCategory, ...]
    reference: NonEmptyText
    transcript: str | None = None
    normalized_reference: NonEmptyText
    normalized_transcript: str | None = None
    status: Literal["completed", "failed"]
    wer: EditMetric | None = None
    cer: EditMetric | None = None
    failure: AsrFailure | None = None

    @model_validator(mode="after")
    def evidence_matches_status(self) -> Self:
        if not self.categories or len(self.categories) != len(set(self.categories)):
            raise ValueError("ASR sample categories must be non-empty and unique")
        if self.normalized_reference != normalize_comparison_text(self.reference):
            raise ValueError("ASR sample normalized reference does not match its raw reference")
        if self.status == "completed":
            if (
                self.transcript is None
                or self.normalized_transcript is None
                or self.wer is None
                or self.cer is None
                or self.failure is not None
            ):
                raise ValueError("completed ASR samples require transcript metrics and no failure")
            expected_transcript = normalize_comparison_text(self.transcript)
            if self.normalized_transcript != expected_transcript:
                raise ValueError(
                    "ASR sample normalized transcript does not match its raw transcript"
                )
            if self.wer != word_error_rate(
                self.normalized_reference, expected_transcript
            ) or self.cer != character_error_rate(self.normalized_reference, expected_transcript):
                raise ValueError("ASR sample metrics do not match its normalized evidence")
        elif (
            self.transcript is not None
            or self.normalized_transcript is not None
            or self.wer is not None
            or self.cer is not None
            or self.failure is None
        ):
            raise ValueError("failed ASR samples require only an actionable failure")
        return self


class AsrAggregate(ContractModel):
    """Weighted edit totals over a sample group."""

    sample_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    wer: EditMetric
    cer: EditMetric

    @model_validator(mode="after")
    def counts_match(self) -> Self:
        if self.completed_count + self.failure_count != self.sample_count:
            raise ValueError("ASR aggregate completed and failure counts must add up")
        return self


class AsrQualificationResult(ContractModel):
    """Strict persistent evidence for one TTS candidate's ASR qualification."""

    schema_version: Literal["asr-qualification-result/v1"] = "asr-qualification-result/v1"
    status: Literal["completed", "partial", "failed"]
    candidate_name: Identifier
    engine: Identifier
    source_tts_result_sha256: Sha256
    corpus_sha256: Sha256
    asr: AsrCandidateConfig
    settings: AsrSettings
    samples: tuple[AsrQualificationSample, ...] = Field(min_length=24, max_length=24)
    overall: AsrAggregate
    by_engine: dict[str, AsrAggregate]
    by_category: dict[CorpusCategory, AsrAggregate]

    @model_validator(mode="after")
    def result_is_internally_consistent(self) -> Self:
        _validate_pinned_asr(self.asr)
        identifiers = [sample.excerpt_id for sample in self.samples]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("ASR sample excerpt identifiers must be unique")
        failures = sum(sample.status == "failed" for sample in self.samples)
        expected_status = (
            "completed"
            if failures == 0
            else "failed"
            if failures == len(self.samples)
            else "partial"
        )
        if self.status != expected_status:
            raise ValueError(f"ASR qualification status must be {expected_status!r}")
        expected_overall = _aggregate(self.samples)
        if self.overall != expected_overall:
            raise ValueError("ASR overall aggregate does not match sample metrics")
        if self.by_engine != {self.engine: expected_overall}:
            raise ValueError("ASR engine aggregate must contain only the scored engine")
        expected_categories = {
            category: _aggregate(
                tuple(sample for sample in self.samples if category in sample.categories)
            )
            for category in sorted(
                {category for sample in self.samples for category in sample.categories},
                key=lambda item: item.value,
            )
        }
        if self.by_category != expected_categories:
            raise ValueError("ASR category aggregates do not match sample metrics")
        return self


class AsrQualificationSummary(ContractModel):
    """Canonical machine-readable summary emitted by score-tts-asr."""

    schema_version: Literal["asr-qualification-summary/v1"] = "asr-qualification-summary/v1"
    status: Literal["completed", "partial", "failed"]
    candidate_name: Identifier
    engine: Identifier
    source_tts_result_sha256: Sha256
    sample_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    result_path: NonEmptyText
    result_sha256: Sha256
    report_path: NonEmptyText
    report_sha256: Sha256

    @model_validator(mode="after")
    def counts_match(self) -> Self:
        if self.completed_count + self.failure_count != self.sample_count:
            raise ValueError("ASR summary completed and failure counts must add up")
        expected_status = (
            "completed"
            if self.failure_count == 0
            else "failed"
            if self.failure_count == self.sample_count
            else "partial"
        )
        if self.status != expected_status:
            raise ValueError(f"ASR summary status must be {expected_status!r}")
        return self


class AsrDependencies(NamedTuple):
    """Injected lazy dependency boundary used by unit tests."""

    snapshot_download: Callable[..., str]
    transcribe: Callable[..., object]


@dataclass(frozen=True)
class _ValidatedInput:
    excerpt: CorpusExcerpt
    wav_path: Path


def score_tts_asr(
    candidate_name: str,
    project_root: Path,
    *,
    dependencies: AsrDependencies | None = None,
) -> AsrQualificationSummary:
    """Validate a complete TTS run, then score it sequentially in one ASR process."""

    root = project_root.expanduser().resolve()
    try:
        TypeAdapter(Identifier).validate_python(candidate_name)
    except ValidationError as error:
        raise QualificationError(
            f"invalid TTS candidate name {candidate_name!r}; use a qualified candidate name"
        ) from error
    asr = load_asr_candidate(candidate_path(root, "asr"))
    _validate_pinned_asr(asr)
    corpus = load_corpus(default_corpus_path(root))
    source_path = root / "work" / "tts-qualification" / candidate_name / "result.json"
    source_bytes = _read_source_result(source_path)
    source_result = load_qualification_result(source_path)
    validated_inputs = _validate_source_result(
        candidate_name,
        source_path,
        source_result,
        corpus,
    )
    loaded_dependencies = dependencies or _import_dependencies()
    snapshot = _resolve_snapshot(loaded_dependencies, asr)
    return _score_validated_inputs(
        candidate_name=candidate_name,
        engine=source_result.engine,
        project_root=root,
        source_result_sha256=sha256_bytes(source_bytes),
        corpus=corpus,
        asr=asr,
        snapshot=snapshot,
        inputs=validated_inputs,
        transcribe=loaded_dependencies.transcribe,
    )


def transcribe_wav(wav_path: Path, asr: AsrCandidateConfig) -> str:
    """Transcribe one validated WAV for the opt-in ASR hardware smoke test."""

    _validate_pinned_asr(asr)
    try:
        data = wav_path.expanduser().resolve().read_bytes()
    except OSError as error:
        raise QualificationError(f"cannot read ASR smoke-test WAV {wav_path}: {error}") from error
    validate_wav_bytes(data)
    dependencies = _import_dependencies()
    snapshot = _resolve_snapshot(dependencies, asr)
    return _transcript_text(
        dependencies.transcribe(
            str(wav_path.expanduser().resolve()),
            **_transcribe_kwargs(snapshot),
        )
    )


def render_asr_report(result: AsrQualificationResult) -> str:
    """Render aggregate evidence, all failures, and only nonzero worst successes."""

    failures = [sample for sample in result.samples if sample.failure is not None]
    worst = sorted(
        (
            sample
            for sample in result.samples
            if sample.wer is not None
            and sample.cer is not None
            and (sample.wer.rate > 0 or sample.cer.rate > 0)
        ),
        key=lambda sample: (
            -cast(EditMetric, sample.wer).rate,
            -cast(EditMetric, sample.cer).rate,
            sample.excerpt_id,
        ),
    )[:5]
    lines = [
        f"# ASR qualification: {result.candidate_name}",
        "",
        f"- Status: `{result.status}`.",
        f"- Engine: `{result.engine}`.",
        f"- ASR model: `{result.asr.model_id}@{result.asr.revision}`.",
        f"- Source TTS result SHA-256: `{result.source_tts_result_sha256}`.",
        f"- Completed excerpts: {result.overall.completed_count}/{result.overall.sample_count}.",
        f"- Weighted WER: {result.overall.wer.rate:.6f}.",
        f"- Weighted CER: {result.overall.cer.rate:.6f}.",
        "",
        "## Category metrics",
        "",
    ]
    lines.extend(
        f"- `{category.value}`: WER {aggregate.wer.rate:.6f}, "
        f"CER {aggregate.cer.rate:.6f}, failures {aggregate.failure_count}."
        for category, aggregate in sorted(
            result.by_category.items(), key=lambda item: item[0].value
        )
    )
    lines.extend(["", "## Failures", ""])
    if not failures:
        lines.append("- None.")
    else:
        for sample in failures:
            assert sample.failure is not None
            lines.append(
                f"- `{sample.excerpt_id}`: {sample.failure.exception_type}: "
                f"{sample.failure.message}"
            )
    lines.extend(["", "## Worst nonzero samples", ""])
    if not worst:
        lines.append("- None.")
    else:
        for sample in worst:
            assert sample.wer is not None
            assert sample.cer is not None
            lines.append(
                f"- `{sample.excerpt_id}`: WER {sample.wer.rate:.6f}, CER {sample.cer.rate:.6f}."
            )
    return "\n".join(lines).rstrip() + "\n"


def _score_validated_inputs(
    *,
    candidate_name: str,
    engine: str,
    project_root: Path,
    source_result_sha256: str,
    corpus: QualificationCorpus,
    asr: AsrCandidateConfig,
    snapshot: str,
    inputs: tuple[_ValidatedInput, ...],
    transcribe: Callable[..., object],
) -> AsrQualificationSummary:
    samples = tuple(
        _score_sample(item, snapshot=snapshot, transcribe=transcribe) for item in inputs
    )
    failed_count = sum(sample.status == "failed" for sample in samples)
    status: Literal["completed", "partial", "failed"] = (
        "completed"
        if failed_count == 0
        else "failed"
        if failed_count == len(samples)
        else "partial"
    )
    overall = _aggregate(samples)
    result = AsrQualificationResult(
        status=status,
        candidate_name=candidate_name,
        engine=engine,
        source_tts_result_sha256=source_result_sha256,
        corpus_sha256=canonical_sha256(corpus),
        asr=asr,
        settings=AsrSettings(),
        samples=samples,
        overall=overall,
        by_engine={engine: overall},
        by_category={
            category: _aggregate(
                tuple(sample for sample in samples if category in sample.categories)
            )
            for category in sorted(
                {category for sample in samples for category in sample.categories},
                key=lambda item: item.value,
            )
        },
    )
    output_root = project_root / "work" / "tts-qualification" / "asr" / candidate_name
    store = ArtifactStore(output_root)
    result_reference = store.write_bytes(RESULT_PATH, canonical_json_bytes(result) + b"\n")
    report_reference = store.write_bytes(
        REPORT_PATH,
        render_asr_report(result).encode("utf-8"),
    )
    return AsrQualificationSummary(
        status=status,
        candidate_name=candidate_name,
        engine=engine,
        source_tts_result_sha256=source_result_sha256,
        sample_count=len(samples),
        completed_count=len(samples) - failed_count,
        failure_count=failed_count,
        result_path=result_reference.path,
        result_sha256=result_reference.sha256,
        report_path=report_reference.path,
        report_sha256=report_reference.sha256,
    )


def _score_sample(
    item: _ValidatedInput,
    *,
    snapshot: str,
    transcribe: Callable[..., object],
) -> AsrQualificationSample:
    reference = item.excerpt.spoken_text
    normalized_reference = normalize_comparison_text(reference)
    try:
        response = transcribe(str(item.wav_path), **_transcribe_kwargs(snapshot))
        transcript = _transcript_text(response)
        normalized_transcript = normalize_comparison_text(transcript)
        return AsrQualificationSample(
            excerpt_id=item.excerpt.excerpt_id,
            categories=item.excerpt.categories,
            reference=reference,
            transcript=transcript,
            normalized_reference=normalized_reference,
            normalized_transcript=normalized_transcript,
            status="completed",
            wer=word_error_rate(normalized_reference, normalized_transcript),
            cer=character_error_rate(normalized_reference, normalized_transcript),
        )
    except Exception as error:
        return AsrQualificationSample(
            excerpt_id=item.excerpt.excerpt_id,
            categories=item.excerpt.categories,
            reference=reference,
            normalized_reference=normalized_reference,
            status="failed",
            failure=AsrFailure(
                exception_type=type(error).__name__,
                message=(
                    "MLX-Whisper transcription failed; inspect this WAV and rerun "
                    f"`bilbo score-tts-asr {item.wav_path.parent.parent.name}`: "
                    f"{str(error) or repr(error)}"
                ),
            ),
        )


def _validate_source_result(
    candidate_name: str,
    source_path: Path,
    result: QualificationResult,
    corpus: QualificationCorpus,
) -> tuple[_ValidatedInput, ...]:
    if result.candidate_name != candidate_name:
        raise QualificationError(
            f"TTS result candidate {result.candidate_name!r} does not match requested "
            f"candidate {candidate_name!r}"
        )
    if result.status != "completed":
        raise QualificationError(
            f"ASR scoring requires a completed 24-sample TTS result; {source_path} "
            f"has status {result.status!r}. Rerun `bilbo qualify-tts {candidate_name}` first"
        )
    corpus_sha256 = canonical_sha256(corpus)
    if result.corpus_sha256 != corpus_sha256:
        raise QualificationError(
            f"TTS result corpus checksum does not match the committed corpus: expected "
            f"{corpus_sha256}, got {result.corpus_sha256}. Regenerate the TTS qualification"
        )
    if len(result.samples) != len(corpus.excerpts):
        raise QualificationError("ASR scoring requires exactly 24 TTS qualification samples")

    source_store = ArtifactStore(source_path.parent)
    validated: list[_ValidatedInput] = []
    for sample, excerpt in zip(result.samples, corpus.excerpts, strict=True):
        _validate_sample_against_corpus(sample, excerpt)
        assert sample.wav_path is not None
        assert sample.wav_sha256 is not None
        assert sample.audio is not None
        wav_path = source_store.resolve(sample.wav_path)
        try:
            wav_data = wav_path.read_bytes()
        except OSError as error:
            raise QualificationError(
                f"cannot read TTS qualification WAV for {sample.excerpt_id}: {wav_path}: {error}"
            ) from error
        actual_checksum = sha256_bytes(wav_data)
        if not hmac.compare_digest(actual_checksum, sample.wav_sha256):
            raise QualificationError(
                f"TTS qualification WAV checksum mismatch for {sample.excerpt_id}: "
                f"expected {sample.wav_sha256}, got {actual_checksum}. Regenerate "
                f"`bilbo qualify-tts {candidate_name}` before ASR scoring"
            )
        try:
            metadata = validate_wav_bytes(
                wav_data,
                expected_sample_rate_hz=sample.settings.sample_rate_hz,
            )
        except AudioValidationError as error:
            raise QualificationError(
                f"invalid TTS qualification WAV for {sample.excerpt_id}: {error}. "
                f"Regenerate `bilbo qualify-tts {candidate_name}` before ASR scoring"
            ) from error
        if metadata != sample.audio:
            raise QualificationError(
                f"TTS qualification WAV metadata changed for {sample.excerpt_id}. "
                f"Regenerate `bilbo qualify-tts {candidate_name}` before ASR scoring"
            )
        validated.append(_ValidatedInput(excerpt=excerpt, wav_path=wav_path.resolve()))
    return tuple(validated)


def _validate_sample_against_corpus(
    sample: QualificationSample,
    excerpt: CorpusExcerpt,
) -> None:
    if sample.status != "completed":
        raise QualificationError(
            f"ASR scoring requires completed TTS samples; {sample.excerpt_id} is failed"
        )
    if sample.excerpt_id != excerpt.excerpt_id:
        raise QualificationError(
            f"TTS result sample order does not match the committed corpus: expected "
            f"{excerpt.excerpt_id}, got {sample.excerpt_id}"
        )
    if sample.categories != excerpt.categories:
        raise QualificationError(
            f"TTS result categories do not match the committed corpus for {excerpt.excerpt_id}"
        )
    expected_text_sha256 = sha256_bytes(excerpt.spoken_text.encode("utf-8"))
    if sample.spoken_text_sha256 != expected_text_sha256:
        raise QualificationError(
            f"TTS result reference text checksum does not match the committed corpus for "
            f"{excerpt.excerpt_id}. Regenerate the TTS qualification"
        )


def _aggregate(samples: tuple[AsrQualificationSample, ...]) -> AsrAggregate:
    completed = tuple(sample for sample in samples if sample.status == "completed")
    return AsrAggregate(
        sample_count=len(samples),
        completed_count=len(completed),
        failure_count=len(samples) - len(completed),
        wer=_sum_metrics(tuple(cast(EditMetric, sample.wer) for sample in completed)),
        cer=_sum_metrics(tuple(cast(EditMetric, sample.cer) for sample in completed)),
    )


def _sum_metrics(metrics: tuple[EditMetric, ...]) -> EditMetric:
    substitutions = sum(metric.substitutions for metric in metrics)
    deletions = sum(metric.deletions for metric in metrics)
    insertions = sum(metric.insertions for metric in metrics)
    denominator = sum(metric.denominator for metric in metrics)
    edits = substitutions + deletions + insertions
    rate = edits / denominator if denominator else float(insertions)
    return EditMetric(
        substitutions=substitutions,
        deletions=deletions,
        insertions=insertions,
        denominator=denominator,
        rate=rate,
    )


def _validate_pinned_asr(asr: AsrCandidateConfig) -> None:
    if asr.model_id != MODEL_ID or asr.revision != MODEL_REVISION:
        raise QualificationError(
            f"ASR qualification requires pinned model {MODEL_ID}@{MODEL_REVISION}; "
            f"got {asr.model_id}@{asr.revision}"
        )
    if asr.engine != "mlx-whisper" or asr.backend != "mlx" or asr.language != "it":
        raise QualificationError("ASR qualification requires the committed Italian MLX config")


def _read_source_result(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise QualificationError(
            f"cannot read TTS qualification result {path}: {error}. Run the TTS "
            "qualification to completion before ASR scoring"
        ) from error


def _import_dependencies() -> AsrDependencies:
    try:
        hub = import_module("huggingface_hub")
        whisper = import_module("mlx_whisper")
        snapshot_download = cast(Callable[..., str], hub.snapshot_download)
        transcribe = cast(Callable[..., object], whisper.transcribe)
    except Exception as error:
        raise QualificationError(
            "MLX-Whisper dependencies could not be imported; run this command with "
            f"`pixi run -e asr`: {error}"
        ) from error
    return AsrDependencies(snapshot_download=snapshot_download, transcribe=transcribe)


def _resolve_snapshot(dependencies: AsrDependencies, asr: AsrCandidateConfig) -> str:
    try:
        snapshot = dependencies.snapshot_download(
            repo_id=asr.model_id,
            revision=asr.revision,
        )
    except Exception as error:
        raise QualificationError(
            f"failed to resolve pinned ASR model {asr.model_id}@{asr.revision}: {error}"
        ) from error
    if not isinstance(snapshot, str) or not snapshot:
        raise QualificationError("pinned ASR model resolution returned an invalid local path")
    return snapshot


def _transcribe_kwargs(snapshot: str) -> dict[str, object]:
    return {
        "path_or_hf_repo": snapshot,
        "language": "it",
        "task": "transcribe",
        "temperature": 0.0,
        "fp16": True,
        "verbose": None,
        "word_timestamps": False,
    }


def _transcript_text(response: object) -> str:
    if not isinstance(response, Mapping):
        raise QualificationError("MLX-Whisper returned a non-mapping transcription result")
    text = response.get("text")
    if not isinstance(text, str):
        raise QualificationError("MLX-Whisper transcription result is missing string field 'text'")
    return text
