"""Narrow contracts shared by automatic speech recognition adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


class AsrError(ValueError):
    """An ASR adapter configuration or result is invalid."""


@runtime_checkable
class Transcriber(Protocol):
    """Convert one audio file into plain transcript text."""

    def transcribe(self, wav_path: Path) -> str:
        """Transcribe one WAV file."""
