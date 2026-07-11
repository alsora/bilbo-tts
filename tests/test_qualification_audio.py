from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from bilbo_tts.config import VoiceConfig
from bilbo_tts.models import SynthesisSettings
from bilbo_tts.qualification.audio import (
    AudioValidationError,
    pcm_wav_bytes,
    validate_wav_bytes,
    validate_wav_file,
)
from bilbo_tts.tts import FakeTtsEngine, TtsRequest, TtsResult


def fake_result() -> TtsResult:
    engine = FakeTtsEngine()
    return engine.synthesize(
        TtsRequest(
            spoken_text="Prova.",
            voice=VoiceConfig(voice_id="fake-voice"),
            settings=SynthesisSettings(sample_rate_hz=24_000, seed=1),
        )
    )


def wav_bytes(*, channels: int = 1, width: int = 2, rate: int = 24_000, frames: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(frames)
    return buffer.getvalue()


def test_pcm_wav_round_trip_and_file_validation(tmp_path: Path) -> None:
    result = fake_result()
    data = pcm_wav_bytes(result)
    metadata = validate_wav_bytes(data, expected_sample_rate_hz=24_000)
    path = tmp_path / "sample.wav"
    path.write_bytes(data)

    assert metadata.channels == 1
    assert metadata.sample_width_bytes == 2
    assert metadata.frame_count > 0
    assert validate_wav_file(path) == metadata


@pytest.mark.parametrize(
    "data,match",
    [
        (b"not wav", "invalid or unreadable"),
        (wav_bytes(channels=2, frames=b"\0" * 8), "must be mono"),
        (wav_bytes(width=1, frames=b"\0" * 4), "16-bit"),
        (wav_bytes(frames=b""), "at least one"),
    ],
)
def test_wav_validation_rejects_invalid_audio(data: bytes, match: str) -> None:
    with pytest.raises(AudioValidationError, match=match):
        validate_wav_bytes(data)


def test_wav_validation_rejects_rate_mismatch_and_missing_file(tmp_path: Path) -> None:
    data = wav_bytes(frames=b"\0\0")
    with pytest.raises(AudioValidationError, match="does not match expected"):
        validate_wav_bytes(data, expected_sample_rate_hz=48_000)
    with pytest.raises(AudioValidationError, match="cannot read"):
        validate_wav_file(tmp_path / "missing.wav")
