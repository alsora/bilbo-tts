"""Narrow text-to-speech contracts and engines."""

from bilbo_tts.tts.contracts import (
    TtsCapabilities,
    TtsEngine,
    TtsError,
    TtsHealth,
    TtsRequest,
    TtsResult,
    VoiceMode,
)
from bilbo_tts.tts.fake import FakeTtsEngine

__all__ = [
    "FakeTtsEngine",
    "TtsCapabilities",
    "TtsEngine",
    "TtsError",
    "TtsHealth",
    "TtsRequest",
    "TtsResult",
    "VoiceMode",
]
