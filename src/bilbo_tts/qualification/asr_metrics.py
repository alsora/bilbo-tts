"""Deterministic text normalization and dependency-free ASR edit metrics."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import Field, model_validator

from bilbo_tts.models import ContractModel

_APOSTROPHES = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "‛": "'",
        "ʼ": "'",
        "＇": "'",
        "`": "'",
        "´": "'",
    }
)


class EditMetric(ContractModel):
    """Exact Levenshtein operation counts and their reference-weighted rate."""

    substitutions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    insertions: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def rate_matches_counts(self) -> EditMetric:
        edits = self.substitutions + self.deletions + self.insertions
        expected = edits / self.denominator if self.denominator else float(self.insertions)
        if self.rate != expected:
            raise ValueError("edit rate must match operation counts and reference denominator")
        return self


@dataclass(frozen=True)
class _Counts:
    substitutions: int = 0
    deletions: int = 0
    insertions: int = 0

    @property
    def edits(self) -> int:
        return self.substitutions + self.deletions + self.insertions


def normalize_comparison_text(text: str) -> str:
    """Normalize both ASR references and transcripts with the same fixed policy."""

    normalized = unicodedata.normalize("NFC", text).casefold().translate(_APOSTROPHES)
    punctuation_normalized = "".join(
        character
        if character == "'" or not unicodedata.category(character).startswith("P")
        else " "
        for character in normalized
    )
    decomposed = unicodedata.normalize("NFD", punctuation_normalized)
    accent_equivalent = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    return " ".join(unicodedata.normalize("NFC", accent_equivalent).split())


def word_error_rate(reference: str, transcript: str) -> EditMetric:
    """Return exact word-level edits after deterministic comparison normalization."""

    return _edit_metric(reference.split(), transcript.split())


def character_error_rate(reference: str, transcript: str) -> EditMetric:
    """Return exact character edits, excluding normalized whitespace."""

    reference_characters = tuple(character for character in reference if not character.isspace())
    transcript_characters = tuple(character for character in transcript if not character.isspace())
    return _edit_metric(reference_characters, transcript_characters)


def _edit_metric(reference: Sequence[str], transcript: Sequence[str]) -> EditMetric:
    counts = _levenshtein_counts(reference, transcript)
    denominator = len(reference)
    rate = counts.edits / denominator if denominator else float(counts.insertions)
    return EditMetric(
        substitutions=counts.substitutions,
        deletions=counts.deletions,
        insertions=counts.insertions,
        denominator=denominator,
        rate=rate,
    )


def _levenshtein_counts(reference: Sequence[str], transcript: Sequence[str]) -> _Counts:
    previous = [_Counts(insertions=index) for index in range(len(transcript) + 1)]
    for reference_index, expected in enumerate(reference, start=1):
        current = [_Counts(deletions=reference_index)]
        for transcript_index, actual in enumerate(transcript, start=1):
            if expected == actual:
                current.append(previous[transcript_index - 1])
                continue
            substitution = previous[transcript_index - 1]
            deletion = previous[transcript_index]
            insertion = current[transcript_index - 1]
            candidates = (
                _Counts(
                    substitutions=substitution.substitutions + 1,
                    deletions=substitution.deletions,
                    insertions=substitution.insertions,
                ),
                _Counts(
                    substitutions=deletion.substitutions,
                    deletions=deletion.deletions + 1,
                    insertions=deletion.insertions,
                ),
                _Counts(
                    substitutions=insertion.substitutions,
                    deletions=insertion.deletions,
                    insertions=insertion.insertions + 1,
                ),
            )
            current.append(
                min(
                    candidates,
                    key=lambda candidate: (
                        candidate.edits,
                        candidate.deletions + candidate.insertions,
                        candidate.deletions,
                        candidate.insertions,
                    ),
                )
            )
        previous = current
    return previous[-1]
