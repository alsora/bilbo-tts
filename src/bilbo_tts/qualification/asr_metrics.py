"""Deterministic text normalization and dependency-free ASR edit metrics."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from bilbo_tts.models import AlignmentEdit, ContractModel

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
AlignmentOperation = Literal["match", "insert", "delete", "substitute"]


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


@dataclass(frozen=True)
class WordAlignment:
    """Human-readable word edits and boundary deletions from one alignment."""

    edits: tuple[AlignmentEdit, ...]
    missing_prefix_words: int
    missing_suffix_words: int


@dataclass(frozen=True)
class _AlignmentStep:
    operation: AlignmentOperation
    expected: str
    actual: str


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


def align_words(reference: str, transcript: str) -> WordAlignment:
    """Return deterministic word edits and missing leading/trailing word counts."""

    steps = _alignment_steps(reference.split(), transcript.split())
    edits: list[AlignmentEdit] = []
    for step in steps:
        if step.operation == "match":
            continue
        edits.append(
            AlignmentEdit(
                operation=step.operation,
                expected=step.expected,
                actual=step.actual,
            )
        )
    missing_prefix = 0
    for step in steps:
        if step.operation == "delete":
            missing_prefix += 1
        elif step.operation != "insert":
            break
    missing_suffix = 0
    for step in reversed(steps):
        if step.operation == "delete":
            missing_suffix += 1
        elif step.operation != "insert":
            break
    return WordAlignment(
        edits=tuple(edits),
        missing_prefix_words=missing_prefix,
        missing_suffix_words=missing_suffix,
    )


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


def _alignment_steps(
    reference: Sequence[str], transcript: Sequence[str]
) -> tuple[_AlignmentStep, ...]:
    counts: list[list[_Counts]] = [
        [_Counts() for _ in range(len(transcript) + 1)] for _ in range(len(reference) + 1)
    ]
    choices: list[list[AlignmentOperation | None]] = [
        [None for _ in range(len(transcript) + 1)] for _ in range(len(reference) + 1)
    ]
    for transcript_index in range(1, len(transcript) + 1):
        counts[0][transcript_index] = _Counts(insertions=transcript_index)
        choices[0][transcript_index] = "insert"
    for reference_index in range(1, len(reference) + 1):
        counts[reference_index][0] = _Counts(deletions=reference_index)
        choices[reference_index][0] = "delete"

    for reference_index, expected in enumerate(reference, start=1):
        for transcript_index, actual in enumerate(transcript, start=1):
            if expected == actual:
                counts[reference_index][transcript_index] = counts[reference_index - 1][
                    transcript_index - 1
                ]
                choices[reference_index][transcript_index] = "match"
                continue
            substitution = counts[reference_index - 1][transcript_index - 1]
            deletion = counts[reference_index - 1][transcript_index]
            insertion = counts[reference_index][transcript_index - 1]
            candidates: tuple[tuple[_Counts, AlignmentOperation], ...] = (
                (
                    _Counts(
                        substitutions=substitution.substitutions + 1,
                        deletions=substitution.deletions,
                        insertions=substitution.insertions,
                    ),
                    "substitute",
                ),
                (
                    _Counts(
                        substitutions=deletion.substitutions,
                        deletions=deletion.deletions + 1,
                        insertions=deletion.insertions,
                    ),
                    "delete",
                ),
                (
                    _Counts(
                        substitutions=insertion.substitutions,
                        deletions=insertion.deletions,
                        insertions=insertion.insertions + 1,
                    ),
                    "insert",
                ),
            )
            selected, operation = min(
                candidates,
                key=lambda candidate: (
                    candidate[0].edits,
                    candidate[0].deletions + candidate[0].insertions,
                    candidate[0].deletions,
                    candidate[0].insertions,
                ),
            )
            counts[reference_index][transcript_index] = selected
            choices[reference_index][transcript_index] = operation

    steps: list[_AlignmentStep] = []
    reference_index = len(reference)
    transcript_index = len(transcript)
    while reference_index or transcript_index:
        current_operation = choices[reference_index][transcript_index]
        assert current_operation is not None
        if current_operation in {"match", "substitute"}:
            steps.append(
                _AlignmentStep(
                    operation=current_operation,
                    expected=reference[reference_index - 1],
                    actual=transcript[transcript_index - 1],
                )
            )
            reference_index -= 1
            transcript_index -= 1
        elif current_operation == "delete":
            steps.append(
                _AlignmentStep(
                    operation=current_operation,
                    expected=reference[reference_index - 1],
                    actual="",
                )
            )
            reference_index -= 1
        else:
            steps.append(
                _AlignmentStep(
                    operation=current_operation,
                    expected="",
                    actual=transcript[transcript_index - 1],
                )
            )
            transcript_index -= 1
    steps.reverse()
    return tuple(steps)
