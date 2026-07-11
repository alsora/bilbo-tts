"""Persistent qualification result and CLI summary contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Self, cast

from pydantic import Field, JsonValue, ValidationError, model_validator

from bilbo_tts.models import (
    ContractModel,
    Identifier,
    ModelIdentity,
    NonEmptyText,
    Sha256,
    SynthesisSettings,
    VoiceIdentity,
)
from bilbo_tts.qualification.audio import WavMetadata
from bilbo_tts.qualification.candidates import TtsCandidateConfig
from bilbo_tts.qualification.corpus import CorpusCategory
from bilbo_tts.tts import TtsHealth


class QualificationError(ValueError):
    """A qualification run cannot start or its result cannot be loaded."""


class QualificationFailure(ContractModel):
    """One actionable per-excerpt generation failure."""

    exception_type: NonEmptyText
    message: NonEmptyText


class QualificationSample(ContractModel):
    """Auditable result for one corpus excerpt."""

    excerpt_id: Identifier
    categories: tuple[CorpusCategory, ...]
    spoken_text_sha256: Sha256
    status: Literal["completed", "failed"]
    model: ModelIdentity
    voice: VoiceIdentity
    settings: SynthesisSettings
    inference_parameters: dict[str, JsonValue]
    generation_seconds: float = Field(ge=0, allow_inf_nan=False)
    wav_path: NonEmptyText | None = None
    wav_sha256: Sha256 | None = None
    audio: WavMetadata | None = None
    real_time_factor: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    failure: QualificationFailure | None = None

    @model_validator(mode="after")
    def completion_fields_match_status(self) -> Self:
        if not self.categories or len(self.categories) != len(set(self.categories)):
            raise ValueError("qualification sample categories must be non-empty and unique")
        success_fields = (self.wav_path, self.wav_sha256, self.audio, self.real_time_factor)
        if self.status == "completed":
            if any(value is None for value in success_fields) or self.failure is not None:
                raise ValueError("completed samples require WAV metadata and no failure")
            assert self.audio is not None
            assert self.real_time_factor is not None
            if self.wav_path != f"audio/{self.excerpt_id}.wav":
                raise ValueError("completed sample WAV path must match its excerpt identifier")
            if self.audio.sample_rate_hz != self.settings.sample_rate_hz:
                raise ValueError("sample WAV rate must match synthesis settings")
            if self.real_time_factor != self.generation_seconds / self.audio.duration_seconds:
                raise ValueError("sample real-time factor does not match timing metadata")
        elif any(value is not None for value in success_fields) or self.failure is None:
            raise ValueError("failed samples require only failure metadata")
        return self


class QualificationResult(ContractModel):
    """Complete qualification evidence for one engine and corpus."""

    schema_version: Literal["tts-qualification-result/v1"] = "tts-qualification-result/v1"
    status: Literal["completed", "partial", "failed"]
    engine: Identifier
    corpus_sha256: Sha256
    candidate: TtsCandidateConfig
    health: TtsHealth
    samples: tuple[QualificationSample, ...] = Field(min_length=24, max_length=24)
    total_generation_seconds: float = Field(ge=0, allow_inf_nan=False)
    total_audio_seconds: float = Field(ge=0, allow_inf_nan=False)
    process_peak_rss_bytes: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_run_consistency(self) -> Self:
        if self.engine != self.candidate.engine:
            raise ValueError("result engine must match candidate engine")
        if (
            self.health.engine != self.engine
            or self.health.model != self.candidate.model
            or not self.health.healthy
        ):
            raise ValueError("result health must be healthy and match the candidate identity")
        identifiers = [sample.excerpt_id for sample in self.samples]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("qualification sample excerpt identifiers must be unique")
        candidate_voice = VoiceIdentity(
            voice_id=self.candidate.voice.voice_id,
            reference_sha256=self.candidate.voice.reference_sha256,
        )
        for sample in self.samples:
            if (
                sample.model != self.candidate.model
                or sample.voice != candidate_voice
                or sample.settings != self.candidate.settings
                or sample.inference_parameters != self.candidate.inference_parameters
            ):
                raise ValueError("qualification sample identity must match the candidate")
        failures = sum(sample.status == "failed" for sample in self.samples)
        expected = (
            "completed"
            if failures == 0
            else "failed"
            if failures == len(self.samples)
            else "partial"
        )
        if self.status != expected:
            raise ValueError(f"qualification status must be {expected!r}")
        expected_generation = sum(sample.generation_seconds for sample in self.samples)
        if self.total_generation_seconds != expected_generation:
            raise ValueError("total generation time does not match sample timings")
        expected_audio = sum(
            sample.audio.duration_seconds for sample in self.samples if sample.audio is not None
        )
        if self.total_audio_seconds != expected_audio:
            raise ValueError("total audio duration does not match sample metadata")
        return self


class TtsQualificationSummary(ContractModel):
    """Canonical machine-readable summary emitted by qualify-tts."""

    schema_version: Literal["tts-qualification-summary/v1"] = "tts-qualification-summary/v1"
    status: Literal["completed", "partial", "failed"]
    engine: Identifier
    corpus_sha256: Sha256
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
            raise ValueError("qualification summary counts must add up")
        return self


def load_qualification_result(path: Path) -> QualificationResult:
    """Load and strictly validate one canonical result JSON file."""

    try:
        raw = json.loads(path.read_bytes())
    except OSError as error:
        raise QualificationError(f"cannot read qualification result {path}: {error}") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise QualificationError(f"invalid JSON in qualification result {path}: {error}") from error
    if not isinstance(raw, dict):
        raise QualificationError(f"qualification result {path} must contain a JSON object")
    try:
        return QualificationResult.model_validate(cast(dict[str, object], raw))
    except ValidationError as error:
        raise QualificationError(f"invalid qualification result {path}:\n{error}") from error
