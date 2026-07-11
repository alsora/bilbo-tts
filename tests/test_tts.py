from __future__ import annotations

import pytest
from pydantic import ValidationError

from bilbo_tts.config import VoiceConfig
from bilbo_tts.models import ModelIdentity, SynthesisSettings
from bilbo_tts.tts import (
    FakeTtsEngine,
    TtsCapabilities,
    TtsError,
    TtsRequest,
    TtsResult,
    VoiceMode,
)
from bilbo_tts.tts.validation import validate_request, validate_result


def request(
    *,
    text: str = "Un testo italiano.",
    seed: int = 7,
    speed: float = 1.0,
    temperature: float | None = 0.5,
    sample_rate: int = 24_000,
    voice: VoiceConfig | None = None,
) -> TtsRequest:
    return TtsRequest(
        spoken_text=text,
        voice=voice or VoiceConfig(voice_id="fake-voice"),
        settings=SynthesisSettings(
            sample_rate_hz=sample_rate,
            seed=seed,
            speed=speed,
            temperature=temperature,
        ),
    )


def test_fake_engine_is_deterministic_and_identity_preserving() -> None:
    engine = FakeTtsEngine()
    first = engine.synthesize(request())
    second = engine.synthesize(request())

    assert first == second
    assert first.model == engine.capabilities.model
    assert first.voice.voice_id == "fake-voice"
    assert first.sample_rate_hz == 24_000
    assert first.frame_count == len(first.pcm_s16le) // 2
    assert first.duration_seconds == first.frame_count / first.sample_rate_hz
    assert engine.health().healthy is True


def test_fake_waveform_changes_with_seed_text_and_speed() -> None:
    engine = FakeTtsEngine()
    baseline = engine.synthesize(request())

    assert engine.synthesize(request(seed=8)).pcm_s16le != baseline.pcm_s16le
    assert engine.synthesize(request(text="Un altro testo.")).pcm_s16le != baseline.pcm_s16le
    assert engine.synthesize(request(speed=2.0)).frame_count < baseline.frame_count


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"sample_rate": 48_000}, "native sample rate"),
        ({"speed": 2.0}, "does not support speed"),
        ({"temperature": 0.5}, "does not support temperature"),
        ({"seed": 1}, "does not support a synthesis seed"),
    ],
)
def test_shared_request_validation_rejects_unsupported_settings(
    changes: dict[str, object],
    match: str,
) -> None:
    capabilities = TtsCapabilities(
        engine="limited",
        model=ModelIdentity(engine="limited", revision="v1"),
        native_sample_rate_hz=24_000,
        voice_modes=(VoiceMode.NAMED,),
        named_voice_ids=("voice",),
        supports_seed=False,
        supports_speed=False,
        supports_temperature=False,
        max_text_characters=20,
    )
    values: dict[str, object] = {
        "text": "Testo",
        "seed": 0,
        "speed": 1.0,
        "temperature": None,
        "sample_rate": 24_000,
        "voice": VoiceConfig(voice_id="voice"),
    }
    values.update(changes)

    with pytest.raises(TtsError, match=match):
        validate_request(capabilities, request(**values))  # type: ignore[arg-type]


def test_shared_request_validation_rejects_voice_modes_and_text_limit() -> None:
    engine = FakeTtsEngine()
    with pytest.raises(TtsError, match="reference voices"):
        validate_request(
            engine.capabilities,
            request(
                voice=VoiceConfig(
                    voice_id="reference",
                    reference_path="voice.wav",
                    reference_sha256="a" * 64,
                )
            ),
        )
    with pytest.raises(TtsError, match="does not support named voice"):
        validate_request(
            engine.capabilities,
            request(voice=VoiceConfig(voice_id="unknown")),
        )
    limited = engine.capabilities.model_copy(update={"max_text_characters": 3})
    with pytest.raises(TtsError, match="at most 3"):
        validate_request(limited, request(text="Troppo lungo"))


def test_contracts_reject_empty_text_invalid_floats_and_pcm_metadata() -> None:
    with pytest.raises(ValidationError):
        request(text=" ")
    with pytest.raises(ValidationError):
        request(speed=0)
    with pytest.raises(ValidationError):
        request(temperature=-0.1)
    with pytest.raises(ValidationError):
        request(speed=float("inf"))

    valid = FakeTtsEngine().synthesize(request())
    payload = valid.model_dump()
    payload["pcm_s16le"] = b"\x00\x00\x00"
    with pytest.raises(ValidationError, match="complete 16-bit frames"):
        TtsResult.model_validate(payload)
    payload = valid.model_dump()
    payload["frame_count"] = valid.frame_count + 1
    with pytest.raises(ValidationError, match="does not match PCM"):
        TtsResult.model_validate(payload)
    payload = valid.model_dump()
    payload["duration_seconds"] = valid.duration_seconds + 1
    with pytest.raises(ValidationError, match="does not exactly match"):
        TtsResult.model_validate(payload)


def test_result_validation_rejects_identity_mismatch() -> None:
    engine = FakeTtsEngine()
    synthesis_request = request()
    result = engine.synthesize(synthesis_request)
    wrong = result.model_copy(update={"model": ModelIdentity(engine="other", revision="v1")})

    with pytest.raises(TtsError, match="model identity"):
        validate_result(engine.capabilities, synthesis_request, wrong)


def test_capabilities_reject_inconsistent_and_duplicate_voice_data() -> None:
    with pytest.raises(ValidationError, match="must match model"):
        TtsCapabilities(
            engine="other",
            model=ModelIdentity(engine="fake", revision="v1"),
            native_sample_rate_hz=24_000,
            voice_modes=(VoiceMode.NAMED,),
            named_voice_ids=("voice",),
            supports_seed=True,
            supports_speed=True,
            supports_temperature=True,
        )
    with pytest.raises(ValidationError, match="must be unique"):
        TtsCapabilities(
            engine="fake",
            model=ModelIdentity(engine="fake", revision="v1"),
            native_sample_rate_hz=24_000,
            voice_modes=(VoiceMode.NAMED,),
            named_voice_ids=("voice", "voice"),
            supports_seed=True,
            supports_speed=True,
            supports_temperature=True,
        )
