"""Minimal explicit TTS engine construction."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import cast

from bilbo_tts.config import SynthesisConfig
from bilbo_tts.models import BackendIdentity
from bilbo_tts.qualification.candidates import (
    TtsCandidateConfig,
    candidate_path,
    fake_candidate,
    load_tts_candidate,
)
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


def resolve_book_candidate(
    synthesis: SynthesisConfig,
    project_root: Path,
) -> TtsCandidateConfig:
    """Resolve and validate the pinned backend selected by one book."""

    if synthesis.engine == "fake":
        candidate = fake_candidate()
    elif synthesis.engine in {"chatterbox", "kokoro"}:
        candidate = load_tts_candidate(candidate_path(project_root, synthesis.engine))
    else:
        raise TtsError(
            f"unsupported synthesis engine {synthesis.engine!r}; "
            "expected fake, chatterbox, or kokoro"
        )
    if candidate.model.revision != synthesis.model_revision:
        raise TtsError(
            f"configured model revision {synthesis.model_revision!r} does not match "
            f"the pinned {candidate.engine} revision {candidate.model.revision!r}"
        )
    return candidate


def backend_identity(candidate: TtsCandidateConfig) -> BackendIdentity:
    """Return the waveform-affecting backend identity for cache addressing."""

    return BackendIdentity(
        backend=candidate.backend,
        model_id=candidate.model_id,
        code_revision=candidate.code_revision,
        inference_parameters=candidate.inference_parameters,
    )
