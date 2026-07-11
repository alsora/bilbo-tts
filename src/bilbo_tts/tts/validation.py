"""Shared request and result validation for TTS engines."""

from __future__ import annotations

from bilbo_tts.models import ModelIdentity, VoiceIdentity
from bilbo_tts.tts.contracts import (
    TtsCapabilities,
    TtsError,
    TtsRequest,
    TtsResult,
    VoiceMode,
)


def voice_identity(request: TtsRequest) -> VoiceIdentity:
    """Derive the persistent voice identity from a request."""

    return VoiceIdentity(
        voice_id=request.voice.voice_id,
        reference_sha256=request.voice.reference_sha256,
    )


def validate_request(capabilities: TtsCapabilities, request: TtsRequest) -> None:
    """Reject request settings unsupported by an engine."""

    settings = request.settings
    if settings.sample_rate_hz != capabilities.native_sample_rate_hz:
        raise TtsError(
            f"{capabilities.engine} requires its native sample rate "
            f"{capabilities.native_sample_rate_hz} Hz, got {settings.sample_rate_hz} Hz"
        )
    if (
        capabilities.max_text_characters is not None
        and len(request.spoken_text) > capabilities.max_text_characters
    ):
        raise TtsError(
            f"{capabilities.engine} accepts at most "
            f"{capabilities.max_text_characters} text characters, "
            f"got {len(request.spoken_text)}"
        )
    if request.voice.reference_path is not None:
        if VoiceMode.REFERENCE not in capabilities.voice_modes:
            raise TtsError(f"{capabilities.engine} does not support reference voices")
    else:
        if VoiceMode.NAMED not in capabilities.voice_modes:
            raise TtsError(f"{capabilities.engine} does not support named voices")
        if (
            capabilities.named_voice_ids
            and request.voice.voice_id not in capabilities.named_voice_ids
        ):
            supported = ", ".join(capabilities.named_voice_ids)
            raise TtsError(
                f"{capabilities.engine} does not support named voice "
                f"{request.voice.voice_id!r}; supported voices: {supported}"
            )
    if not capabilities.supports_seed and settings.seed != 0:
        raise TtsError(f"{capabilities.engine} does not support a synthesis seed")
    if not capabilities.supports_speed and settings.speed != 1.0:
        raise TtsError(f"{capabilities.engine} does not support speed changes")
    if not capabilities.supports_temperature and settings.temperature is not None:
        raise TtsError(f"{capabilities.engine} does not support temperature")


def validate_result(
    capabilities: TtsCapabilities,
    request: TtsRequest,
    result: TtsResult,
) -> None:
    """Reject output that does not exactly match its request and engine."""

    expected_voice = voice_identity(request)
    _require_equal(result.model, capabilities.model, "result model identity")
    _require_equal(result.voice, expected_voice, "result voice identity")
    _require_equal(result.settings, request.settings, "result synthesis settings")
    if result.sample_rate_hz != capabilities.native_sample_rate_hz:
        raise TtsError(
            f"result sample rate {result.sample_rate_hz} Hz does not match native "
            f"sample rate {capabilities.native_sample_rate_hz} Hz"
        )


def _require_equal(
    actual: ModelIdentity | VoiceIdentity | object,
    expected: ModelIdentity | VoiceIdentity | object,
    label: str,
) -> None:
    if actual != expected:
        raise TtsError(f"{label} does not match the synthesis request")
