"""Strict contracts shared by text-to-speech engines."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, Self, runtime_checkable

from pydantic import Field, field_validator, model_validator

from bilbo_tts.config import VoiceConfig
from bilbo_tts.models import (
    ContractModel,
    Identifier,
    ModelIdentity,
    NonEmptyText,
    SynthesisSettings,
    VoiceIdentity,
)


class TtsError(ValueError):
    """A text-to-speech request or result is invalid."""


class VoiceMode(StrEnum):
    """Voice selection modes understood by an engine."""

    NAMED = "named"
    REFERENCE = "reference"


class TtsRequest(ContractModel):
    """One validated synthesis request."""

    spoken_text: NonEmptyText
    voice: VoiceConfig
    settings: SynthesisSettings


class TtsCapabilities(ContractModel):
    """Generation behavior exposed without loading model weights."""

    engine: Identifier
    model: ModelIdentity
    native_sample_rate_hz: int = Field(gt=0)
    voice_modes: tuple[VoiceMode, ...]
    named_voice_ids: tuple[Identifier, ...] = ()
    supports_seed: bool
    supports_speed: bool
    supports_temperature: bool
    max_text_characters: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_voice_modes(self) -> Self:
        if self.engine != self.model.engine:
            raise ValueError("capability engine must match model engine")
        if len(self.voice_modes) != len(set(self.voice_modes)):
            raise ValueError("voice_modes values must be unique")
        if len(self.named_voice_ids) != len(set(self.named_voice_ids)):
            raise ValueError("named_voice_ids values must be unique")
        if self.named_voice_ids and VoiceMode.NAMED not in self.voice_modes:
            raise ValueError("named_voice_ids require named voice support")
        return self


class TtsHealth(ContractModel):
    """Non-generating engine availability report."""

    engine: Identifier
    model: ModelIdentity
    healthy: bool
    detail: NonEmptyText


class TtsResult(ContractModel):
    """Mono signed 16-bit little-endian PCM plus exact generation identity."""

    pcm_s16le: bytes = Field(min_length=2)
    sample_rate_hz: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    model: ModelIdentity
    voice: VoiceIdentity
    settings: SynthesisSettings

    @field_validator("pcm_s16le")
    @classmethod
    def pcm_has_complete_frames(cls, pcm: bytes) -> bytes:
        if len(pcm) % 2:
            raise ValueError("pcm_s16le must contain complete 16-bit frames")
        return pcm

    @model_validator(mode="after")
    def metadata_matches_pcm(self) -> Self:
        expected_frames = len(self.pcm_s16le) // 2
        if self.frame_count != expected_frames:
            raise ValueError(
                f"frame_count {self.frame_count} does not match PCM frame count {expected_frames}"
            )
        expected_duration = self.frame_count / self.sample_rate_hz
        if self.duration_seconds != expected_duration:
            raise ValueError("duration_seconds does not exactly match frame_count / sample_rate_hz")
        if self.settings.sample_rate_hz != self.sample_rate_hz:
            raise ValueError("result settings sample rate does not match result sample rate")
        return self


@runtime_checkable
class TtsEngine(Protocol):
    """Narrow interface implemented by qualification TTS engines."""

    @property
    def capabilities(self) -> TtsCapabilities:
        """Return static engine capabilities without generating audio."""

    def health(self) -> TtsHealth:
        """Return a non-generating availability report."""

    def synthesize(self, request: TtsRequest) -> TtsResult:
        """Generate one normalized mono PCM result."""
