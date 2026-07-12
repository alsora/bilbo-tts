"""Validated pronunciation lexicons and deterministic replacement."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import ValidationError, field_validator, model_validator

from bilbo_tts.config import LexiconConfig
from bilbo_tts.models import (
    AppliedTransformation,
    ContractModel,
    Identifier,
    NonEmptyText,
    Sha256,
)
from bilbo_tts.serialization import canonical_sha256, sha256_bytes

SHARED_LEXICON_DIR = Path(__file__).parents[3] / "config" / "lexicons"
BUILTIN_LEXICON_PATH = SHARED_LEXICON_DIR / "finance-it.yaml"


class LexiconError(ValueError):
    """A configured pronunciation lexicon is invalid or unavailable."""


class LexiconEntry(ContractModel):
    """One literal or regular-expression pronunciation replacement."""

    entry_id: Identifier
    mode: Literal["literal", "regex"]
    pattern: NonEmptyText
    spoken: NonEmptyText
    priority: int = 0
    case_sensitive: bool = False
    word_boundaries: bool = True
    notes: NonEmptyText | None = None

    @model_validator(mode="after")
    def regex_does_not_match_empty_text(self) -> Self:
        if self.mode == "regex":
            try:
                compiled = re.compile(self.pattern)
            except re.error as error:
                raise ValueError(f"invalid regex pattern: {error}") from error
            if compiled.search("") is not None:
                raise ValueError("regex pattern must not match empty text")
        return self


class PronunciationLexicon(ContractModel):
    """Versioned reviewed pronunciation data."""

    schema_version: Literal["pronunciation-lexicon/v1"] = "pronunciation-lexicon/v1"
    lexicon_id: Identifier
    entries: tuple[LexiconEntry, ...] = ()

    @field_validator("entries")
    @classmethod
    def entry_ids_are_unique(cls, entries: tuple[LexiconEntry, ...]) -> tuple[LexiconEntry, ...]:
        ids = [entry.entry_id for entry in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("lexicon entry_id values must be unique")
        return entries


class LoadedLexicon(ContractModel):
    """One lexicon with its exact source checksum."""

    source: NonEmptyText
    sha256: Sha256
    lexicon: PronunciationLexicon


class LoadedLexicons(ContractModel):
    """Ordered lexicons and their combined cache identity."""

    lexicons: tuple[LoadedLexicon, ...]
    sha256: Sha256

    def apply(self, text: str) -> tuple[str, tuple[AppliedTransformation, ...]]:
        """Apply entries by priority and overlay precedence."""

        ordered: list[tuple[int, int, int, PronunciationLexicon, LexiconEntry]] = []
        for lexicon_index, loaded in enumerate(self.lexicons):
            for entry_index, entry in enumerate(loaded.lexicon.entries):
                ordered.append(
                    (
                        -entry.priority,
                        -lexicon_index,
                        entry_index,
                        loaded.lexicon,
                        entry,
                    )
                )
        result = text
        transformations: list[AppliedTransformation] = []
        for _, _, _, lexicon, entry in sorted(ordered, key=lambda item: item[:3]):
            pattern = _entry_pattern(entry)
            before = result
            result, count = pattern.subn(_constant_replacement(entry.spoken), result)
            if count and result != before:
                transformations.append(
                    AppliedTransformation(
                        rule_id=f"lexicon.{lexicon.lexicon_id}.{entry.entry_id}",
                        before=before,
                        after=result,
                    )
                )
        return result, tuple(transformations)


def load_lexicons(book_dir: Path, configured: tuple[LexiconConfig, ...]) -> LoadedLexicons:
    """Load the built-in finance lexicon and checked book or shared overlays."""

    loaded = [_load_path(BUILTIN_LEXICON_PATH, "builtin:finance-it")]
    roots = {
        "book": book_dir.expanduser().resolve(),
        "shared": SHARED_LEXICON_DIR.resolve(),
    }
    for item in configured:
        root = roots[item.scope]
        path = root.joinpath(*Path(item.path).parts).resolve(strict=False)
        if not path.is_relative_to(root):
            raise LexiconError(
                f"configured lexicon escapes the {item.scope} directory: {item.path}"
            )
        lexicon = _load_path(path, f"{item.scope}:{item.path}")
        if lexicon.sha256 != item.sha256:
            raise LexiconError(
                f"lexicon checksum mismatch for {item.path}: "
                f"expected {item.sha256}, got {lexicon.sha256}"
            )
        loaded.append(lexicon)
    combined = canonical_sha256([{"source": item.source, "sha256": item.sha256} for item in loaded])
    return LoadedLexicons(lexicons=tuple(loaded), sha256=combined)


def _load_path(path: Path, source: str) -> LoadedLexicon:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise LexiconError(f"cannot read pronunciation lexicon {path}: {error}") from error
    try:
        raw = yaml.safe_load(data)
        lexicon = PronunciationLexicon.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as error:
        raise LexiconError(f"invalid pronunciation lexicon {path}: {error}") from error
    return LoadedLexicon(source=source, sha256=sha256_bytes(data), lexicon=lexicon)


def _entry_pattern(entry: LexiconEntry) -> re.Pattern[str]:
    source = re.escape(entry.pattern) if entry.mode == "literal" else entry.pattern
    if entry.word_boundaries:
        source = rf"(?<!\w)(?:{source})(?!\w)"
    flags = 0 if entry.case_sensitive else re.IGNORECASE
    return re.compile(source, flags)


def _constant_replacement(spoken: str) -> Callable[[re.Match[str]], str]:
    def replace(_match: re.Match[str]) -> str:
        return spoken

    return replace
