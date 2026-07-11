"""Validated fixed corpus for Italian TTS qualification."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal, Self, cast

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from bilbo_tts.models import ContractModel, Identifier, NonEmptyText


class CorpusError(ValueError):
    """A qualification corpus is unreadable or invalid."""


class CorpusCategory(StrEnum):
    """Required speech-risk categories represented in the fixed corpus."""

    ORDINARY_PROSE = "ordinary-prose"
    DIALOGUE = "dialogue"
    LONG_SENTENCE = "long-sentence"
    PERCENTAGES = "percentages"
    RATIOS = "ratios"
    CURRENCIES = "currencies"
    ABBREVIATIONS = "abbreviations"
    DATES = "dates"
    SECTION_REFERENCES = "section-references"
    ACRONYMS = "acronyms"
    ENGLISH_FINANCE = "english-finance"
    DIFFICULT_FINANCE = "difficult-finance"
    TYPOGRAPHIC_PUNCTUATION = "typographic-punctuation"
    SEMICOLON_COLON = "semicolon-colon"


REQUIRED_CATEGORIES = frozenset(CorpusCategory)


class CorpusExcerpt(ContractModel):
    """One reviewed spoken-text excerpt."""

    excerpt_id: Identifier
    categories: tuple[CorpusCategory, ...]
    spoken_text: NonEmptyText
    notes: NonEmptyText

    @field_validator("categories")
    @classmethod
    def categories_are_nonempty_and_unique(
        cls, categories: tuple[CorpusCategory, ...]
    ) -> tuple[CorpusCategory, ...]:
        if not categories:
            raise ValueError("excerpt categories must not be empty")
        if len(categories) != len(set(categories)):
            raise ValueError("excerpt categories must be unique")
        return categories


class QualificationCorpus(ContractModel):
    """The complete stable qualification corpus."""

    schema_version: Literal["tts-qualification-corpus/v1"] = "tts-qualification-corpus/v1"
    language: Literal["it"] = "it"
    excerpts: tuple[CorpusExcerpt, ...] = Field(min_length=24, max_length=24)

    @model_validator(mode="after")
    def validate_identifiers_and_coverage(self) -> Self:
        identifiers = [excerpt.excerpt_id for excerpt in self.excerpts]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("excerpt_id values must be unique")
        covered = {category for excerpt in self.excerpts for category in excerpt.categories}
        missing = sorted(category.value for category in REQUIRED_CATEGORIES - covered)
        if missing:
            raise ValueError(f"corpus is missing required categories: {', '.join(missing)}")
        return self


def load_corpus(path: Path) -> QualificationCorpus:
    """Load the corpus deterministically with strict schema validation."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CorpusError(f"cannot read qualification corpus {path}: {error}") from error
    except yaml.YAMLError as error:
        raise CorpusError(f"invalid YAML in qualification corpus {path}: {error}") from error
    if not isinstance(raw, dict):
        raise CorpusError(f"qualification corpus {path} must contain a YAML mapping")
    try:
        return QualificationCorpus.model_validate(cast(dict[str, object], raw))
    except ValidationError as error:
        raise CorpusError(f"invalid qualification corpus {path}:\n{error}") from error


def default_corpus_path(project_root: Path) -> Path:
    """Return the committed qualification corpus path."""

    return project_root.expanduser().resolve() / "config" / "qualification" / "corpus.yaml"
