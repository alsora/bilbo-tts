"""Standard-library PCM WAV writing and validation."""

from __future__ import annotations

import io
import wave
from pathlib import Path

from pydantic import Field, model_validator

from bilbo_tts.models import ContractModel
from bilbo_tts.tts import TtsResult


class AudioValidationError(ValueError):
    """A qualification WAV does not satisfy the PCM contract."""


class WavMetadata(ContractModel):
    """Validated mono signed 16-bit PCM WAV metadata."""

    channels: int = Field(gt=0)
    sample_width_bytes: int = Field(gt=0)
    sample_rate_hz: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    duration_seconds: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def duration_matches(self) -> WavMetadata:
        if self.duration_seconds != self.frame_count / self.sample_rate_hz:
            raise ValueError("WAV duration does not match frame count and sample rate")
        return self


def pcm_wav_bytes(result: TtsResult) -> bytes:
    """Wrap normalized PCM bytes in a mono WAV container."""

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(result.sample_rate_hz)
        output.setcomptype("NONE", "not compressed")
        output.writeframes(result.pcm_s16le)
    data = buffer.getvalue()
    validate_wav_bytes(data, expected_sample_rate_hz=result.sample_rate_hz)
    return data


def validate_wav_file(path: Path, *, expected_sample_rate_hz: int | None = None) -> WavMetadata:
    """Read and validate one WAV file."""

    try:
        data = path.read_bytes()
    except OSError as error:
        raise AudioValidationError(f"cannot read WAV file {path}: {error}") from error
    return validate_wav_bytes(data, expected_sample_rate_hz=expected_sample_rate_hz)


def validate_wav_bytes(
    data: bytes,
    *,
    expected_sample_rate_hz: int | None = None,
) -> WavMetadata:
    """Validate readable non-empty mono signed 16-bit PCM WAV bytes."""

    try:
        with wave.open(io.BytesIO(data), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            compression = source.getcomptype()
            frames = source.readframes(frame_count)
    except (EOFError, wave.Error) as error:
        raise AudioValidationError(f"invalid or unreadable WAV data: {error}") from error
    if channels != 1:
        raise AudioValidationError(f"WAV must be mono, got {channels} channels")
    if sample_width != 2:
        raise AudioValidationError(
            f"WAV must use signed 16-bit samples, got {sample_width * 8}-bit samples"
        )
    if compression != "NONE":
        raise AudioValidationError(f"WAV must be uncompressed PCM, got {compression}")
    if sample_rate <= 0:
        raise AudioValidationError(f"WAV sample rate must be positive, got {sample_rate}")
    if expected_sample_rate_hz is not None and sample_rate != expected_sample_rate_hz:
        raise AudioValidationError(
            f"WAV sample rate {sample_rate} Hz does not match expected {expected_sample_rate_hz} Hz"
        )
    if frame_count <= 0:
        raise AudioValidationError("WAV must contain at least one audio frame")
    expected_bytes = frame_count * channels * sample_width
    if len(frames) != expected_bytes:
        raise AudioValidationError(
            f"WAV frame data is truncated: expected {expected_bytes} bytes, got {len(frames)}"
        )
    return WavMetadata(
        channels=channels,
        sample_width_bytes=sample_width,
        sample_rate_hz=sample_rate,
        frame_count=frame_count,
        duration_seconds=frame_count / sample_rate,
    )
