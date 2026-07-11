"""Strict per-book configuration loading."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    Field,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from bilbo_tts.models import (
    ContractModel,
    Identifier,
    NonEmptyText,
    Sha256,
    SourceFormat,
    SynthesisSettings,
)

RelativePath = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ConfigurationError(ValueError):
    """Book configuration cannot be read or validated."""


def _validate_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path must be relative and remain within the book directory")
    if "\\" in value or any(part in {"", "."} for part in value.split("/")):
        raise ValueError("path must use normalized POSIX segments")
    return path.as_posix()


class InputConfig(ContractModel):
    """Book source selection."""

    format: SourceFormat
    path: RelativePath

    @field_validator("path")
    @classmethod
    def path_matches_format(cls, path: str, info: ValidationInfo) -> str:
        normalized = _validate_relative_path(path)
        # Field order guarantees format has already been validated.
        source_format = info.data.get("format")
        suffix = PurePosixPath(normalized).suffix.lower()
        expected = {SourceFormat.LATEX: {".tex"}, SourceFormat.PDF: {".pdf"}}
        if source_format in expected and suffix not in expected[source_format]:
            raise ValueError(f"path extension is incompatible with {source_format} input")
        return normalized


class PresentationMetadata(ContractModel):
    """Metadata that does not affect synthesized audio."""

    title: NonEmptyText
    author: NonEmptyText
    subtitle: NonEmptyText | None = None
    narrator: NonEmptyText | None = None
    cover_path: RelativePath | None = None

    @field_validator("cover_path")
    @classmethod
    def cover_is_relative_image(cls, path: str | None) -> str | None:
        if path is None:
            return None
        normalized = _validate_relative_path(path)
        if PurePosixPath(normalized).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("cover_path must refer to a JPEG or PNG image")
        return normalized


class LexiconConfig(ContractModel):
    """One versioned pronunciation lexicon."""

    path: RelativePath
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def lexicon_is_relative_yaml(cls, path: str) -> str:
        normalized = _validate_relative_path(path)
        if PurePosixPath(normalized).suffix.lower() not in {".yaml", ".yml"}:
            raise ValueError("lexicon path must refer to a YAML file")
        return normalized


class NormalizationConfig(ContractModel):
    """Inputs that define spoken-text normalization."""

    version: NonEmptyText
    lexicons: tuple[LexiconConfig, ...] = ()

    @field_validator("lexicons")
    @classmethod
    def lexicon_paths_are_unique(
        cls, lexicons: tuple[LexiconConfig, ...]
    ) -> tuple[LexiconConfig, ...]:
        paths = [lexicon.path for lexicon in lexicons]
        if len(paths) != len(set(paths)):
            raise ValueError("lexicon paths must be unique")
        return lexicons


class ChunkingConfig(ContractModel):
    """Text limits applied before model qualification."""

    max_characters: int = Field(gt=0)


class VoiceConfig(ContractModel):
    """Configured voice and optional owned reference audio."""

    voice_id: Identifier
    reference_path: RelativePath | None = None
    reference_sha256: Sha256 | None = None

    @field_validator("reference_path")
    @classmethod
    def reference_is_relative_audio(cls, path: str | None) -> str | None:
        if path is None:
            return None
        normalized = _validate_relative_path(path)
        if PurePosixPath(normalized).suffix.lower() not in {".flac", ".wav"}:
            raise ValueError("voice reference must be a FLAC or WAV file")
        return normalized

    @model_validator(mode="after")
    def reference_fields_are_paired(self) -> Self:
        if (self.reference_path is None) != (self.reference_sha256 is None):
            raise ValueError("reference_path and reference_sha256 must be provided together")
        return self


class SynthesisConfig(ContractModel):
    """Model and generation settings for this book."""

    engine: Identifier
    model_revision: NonEmptyText
    voice: VoiceConfig
    settings: SynthesisSettings
    max_retries: int = Field(default=2, ge=0, le=10)


class PauseConfig(ContractModel):
    """Pause durations used during final assembly."""

    sentence_ms: int = Field(default=250, gt=0)
    paragraph_ms: int = Field(default=600, gt=0)
    chapter_ms: int = Field(default=1500, gt=0)


class AssemblyConfig(ContractModel):
    """Final media settings."""

    pauses: PauseConfig = PauseConfig()
    loudness_lufs: float = Field(default=-18.0, ge=-70, le=-5)
    true_peak_db: float = Field(default=-2.0, ge=-10, le=0)


class BookConfig(ContractModel):
    """Complete validated book configuration."""

    schema_version: Literal["book-config/v1"] = "book-config/v1"
    book_id: Identifier
    language: Literal["it"] = "it"
    input: InputConfig
    metadata: PresentationMetadata
    normalization: NormalizationConfig
    chunking: ChunkingConfig
    synthesis: SynthesisConfig
    assembly: AssemblyConfig = AssemblyConfig()


def load_book_config(path: Path) -> BookConfig:
    """Load a YAML configuration with actionable validation errors."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigurationError(f"cannot read book configuration {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigurationError(f"invalid YAML in book configuration {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigurationError(f"book configuration {path} must contain a YAML mapping")
    try:
        return BookConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigurationError(f"invalid book configuration {path}:\n{error}") from error
