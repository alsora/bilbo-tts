"""Minimal explicit TTS engine construction."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import cast

from bilbo_tts.qualification.candidates import TtsCandidateConfig
from bilbo_tts.tts.contracts import TtsEngine, TtsError
from bilbo_tts.tts.fake import FakeTtsEngine


def create_tts_engine(
    candidate: TtsCandidateConfig,
    project_root: Path = Path("."),
) -> TtsEngine:
    """Construct one configured engine while keeping model imports lazy."""

    if candidate.engine == "fake":
        return FakeTtsEngine(
            model=candidate.model,
            sample_rate_hz=candidate.settings.sample_rate_hz,
            voice_id=candidate.voice.voice_id,
        )
    module_name = {
        "chatterbox": "bilbo_tts.tts.chatterbox",
        "kokoro": "bilbo_tts.tts.kokoro",
    }[candidate.engine]
    try:
        module = import_module(module_name)
        factory = cast(
            Callable[[TtsCandidateConfig, Path], TtsEngine],
            module.create_engine,
        )
    except (AttributeError, ImportError) as error:
        raise TtsError(f"cannot import the {candidate.engine} TTS adapter: {error}") from error
    return factory(candidate, project_root.expanduser().resolve())
