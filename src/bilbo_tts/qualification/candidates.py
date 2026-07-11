"""Strict qualification candidate configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self, cast

import yaml
from pydantic import (
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from bilbo_tts.config import VoiceConfig
from bilbo_tts.models import (
    ContractModel,
    Identifier,
    ModelIdentity,
    NonEmptyText,
    SynthesisSettings,
)
from bilbo_tts.serialization import canonical_json_bytes

CandidateEngine = Literal["fake", "chatterbox", "kokoro"]


class CandidateConfigurationError(ValueError):
    """A qualification candidate configuration is unreadable or invalid."""


class TtsCandidateConfig(ContractModel):
    """Exact model, voice, and inference settings for one TTS candidate."""

    schema_version: Literal["tts-candidate/v1"] = "tts-candidate/v1"
    engine: CandidateEngine
    backend: Identifier
    model_id: NonEmptyText
    model: ModelIdentity
    code_revision: NonEmptyText | None = None
    voice: VoiceConfig
    settings: SynthesisSettings
    inference_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    notes: tuple[NonEmptyText, ...] = ()

    @field_validator("inference_parameters")
    @classmethod
    def validate_inference_parameters(
        cls, parameters: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        for name in parameters:
            TypeAdapter(Identifier).validate_python(name)
        canonical_json_bytes(parameters)
        return parameters

    @model_validator(mode="after")
    def identity_matches_engine(self) -> Self:
        if self.model.engine != self.engine:
            raise ValueError("model engine must match candidate engine")
        return self


class AsrCandidateConfig(ContractModel):
    """Exact model configuration for the later qualification scorer."""

    schema_version: Literal["asr-candidate/v1"] = "asr-candidate/v1"
    engine: Literal["mlx-whisper"] = "mlx-whisper"
    backend: Literal["mlx"] = "mlx"
    model_id: NonEmptyText
    revision: NonEmptyText
    language: Literal["it"] = "it"


def load_tts_candidate(path: Path) -> TtsCandidateConfig:
    """Load one strict TTS candidate YAML file."""

    raw = _load_yaml_mapping(path, "TTS candidate")
    try:
        return TtsCandidateConfig.model_validate(raw)
    except ValidationError as error:
        raise CandidateConfigurationError(
            f"invalid TTS candidate configuration {path}:\n{error}"
        ) from error


def load_asr_candidate(path: Path) -> AsrCandidateConfig:
    """Load one strict ASR candidate YAML file."""

    raw = _load_yaml_mapping(path, "ASR candidate")
    try:
        return AsrCandidateConfig.model_validate(raw)
    except ValidationError as error:
        raise CandidateConfigurationError(
            f"invalid ASR candidate configuration {path}:\n{error}"
        ) from error


def candidate_path(project_root: Path, engine: str) -> Path:
    """Resolve a committed candidate configuration by engine name."""

    return project_root.expanduser().resolve() / "config" / "qualification" / f"{engine}.yaml"


def fake_candidate() -> TtsCandidateConfig:
    """Return the explicit dependency-free candidate used by tests."""

    return TtsCandidateConfig(
        engine="fake",
        backend="stdlib",
        model_id="bilbo-tts/fake",
        model=ModelIdentity(engine="fake", revision="fake-v1"),
        voice=VoiceConfig(voice_id="fake-voice"),
        settings=SynthesisSettings(sample_rate_hz=24_000, seed=20_260_711),
        inference_parameters={},
        notes=("Dependency-free deterministic test engine.",),
    )


def _load_yaml_mapping(path: Path, label: str) -> dict[str, object]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CandidateConfigurationError(
            f"cannot read {label} configuration {path}: {error}"
        ) from error
    except yaml.YAMLError as error:
        raise CandidateConfigurationError(
            f"invalid YAML in {label} configuration {path}: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise CandidateConfigurationError(f"{label} configuration {path} must be a YAML mapping")
    return cast(dict[str, object], raw)
