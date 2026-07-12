"""Narrow automatic speech recognition contracts and adapters."""

from bilbo_tts.asr.contracts import AsrError, Transcriber
from bilbo_tts.asr.mlx_whisper import (
    MODEL_ID,
    MODEL_REVISION,
    MlxWhisperConfig,
    MlxWhisperDependencies,
    MlxWhisperTranscriber,
)

__all__ = [
    "MODEL_ID",
    "MODEL_REVISION",
    "AsrError",
    "MlxWhisperConfig",
    "MlxWhisperDependencies",
    "MlxWhisperTranscriber",
    "Transcriber",
]
