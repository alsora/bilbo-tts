"""Deterministic dependency-free TTS engine used by tests."""

from __future__ import annotations

import hashlib
import struct

from bilbo_tts.models import ModelIdentity
from bilbo_tts.tts.contracts import (
    TtsCapabilities,
    TtsHealth,
    TtsRequest,
    TtsResult,
    VoiceMode,
)
from bilbo_tts.tts.validation import validate_request, validate_result, voice_identity


class FakeTtsEngine:
    """Generate deterministic low-amplitude PCM without a model dependency."""

    def __init__(
        self,
        *,
        model: ModelIdentity | None = None,
        sample_rate_hz: int = 24_000,
        voice_id: str = "fake-voice",
    ) -> None:
        identity = model or ModelIdentity(engine="fake", revision="fake-v1")
        self._capabilities = TtsCapabilities(
            engine=identity.engine,
            model=identity,
            native_sample_rate_hz=sample_rate_hz,
            voice_modes=(VoiceMode.NAMED,),
            named_voice_ids=(voice_id,),
            supports_seed=True,
            supports_speed=True,
            supports_temperature=True,
        )

    @property
    def capabilities(self) -> TtsCapabilities:
        """Return fixed fake-engine capabilities."""

        return self._capabilities

    def health(self) -> TtsHealth:
        """Report availability without generating audio."""

        return TtsHealth(
            engine=self.capabilities.engine,
            model=self.capabilities.model,
            healthy=True,
            detail="deterministic fake engine is available",
        )

    def synthesize(self, request: TtsRequest) -> TtsResult:
        """Generate deterministic PCM from the seed and spoken-text hash."""

        validate_request(self.capabilities, request)
        sample_rate = self.capabilities.native_sample_rate_hz
        duration_seconds = max(0.08, len(request.spoken_text) * 0.012 / request.settings.speed)
        frame_count = max(1, round(duration_seconds * sample_rate))
        seed_material = f"{request.settings.seed}\0{request.spoken_text}".encode()
        state = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "little")
        pcm = bytearray(frame_count * 2)
        for frame in range(frame_count):
            state = (state * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
            sample = ((state >> 48) & 0x3FFF) - 8192
            struct.pack_into("<h", pcm, frame * 2, sample)
        result = TtsResult(
            pcm_s16le=bytes(pcm),
            sample_rate_hz=sample_rate,
            frame_count=frame_count,
            duration_seconds=frame_count / sample_rate,
            model=self.capabilities.model,
            voice=voice_identity(request),
            settings=request.settings,
        )
        validate_result(self.capabilities, request, result)
        return result
