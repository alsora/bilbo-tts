from __future__ import annotations

import pytest

from bilbo_tts.qualification.asr_metrics import (
    character_error_rate,
    normalize_comparison_text,
    word_error_rate,
)


@pytest.mark.parametrize(
    ("reference", "transcript", "expected"),
    [
        ("uno due", "uno due", (0, 0, 0, 2, 0.0)),
        ("uno due", "uno tre", (1, 0, 0, 2, 0.5)),
        ("uno due", "uno nuovo due", (0, 0, 1, 2, 0.5)),
        ("uno nuovo due", "uno due", (0, 1, 0, 3, 1 / 3)),
        ("", "", (0, 0, 0, 0, 0.0)),
        ("", "uno due", (0, 0, 2, 0, 2.0)),
        ("uno", "", (0, 1, 0, 1, 1.0)),
    ],
)
def test_word_error_rate_has_exact_edit_counts(
    reference: str,
    transcript: str,
    expected: tuple[int, int, int, int, float],
) -> None:
    metric = word_error_rate(reference, transcript)

    assert (
        metric.substitutions,
        metric.deletions,
        metric.insertions,
        metric.denominator,
    ) == expected[:4]
    assert metric.rate == pytest.approx(expected[4])


def test_character_error_rate_counts_characters_without_whitespace() -> None:
    metric = character_error_rate("casa blu", "cassa blu")

    assert metric.substitutions == 0
    assert metric.deletions == 0
    assert metric.insertions == 1
    assert metric.denominator == 7
    assert metric.rate == pytest.approx(1 / 7)


@pytest.mark.parametrize(
    ("left", "right", "normalized"),
    [
        ("È già tardi", "e gia tardi", "e gia tardi"),
        ("L’economia", "l'economia", "l'economia"),
        ("«CIAO!», disse.", "ciao disse", "ciao disse"),
        ("CAFFÈ", "caffe\u0300", "caffe"),
        ("  uno\t due\n", "uno due", "uno due"),
    ],
)
def test_comparison_normalization_equates_documented_variants(
    left: str,
    right: str,
    normalized: str,
) -> None:
    assert normalize_comparison_text(left) == normalized
    assert normalize_comparison_text(right) == normalized


def test_normalization_is_applied_identically_before_metrics() -> None:
    reference = normalize_comparison_text("L’AZIONE è salita.")
    transcript = normalize_comparison_text("l'azione e salita")

    assert word_error_rate(reference, transcript).rate == 0
    assert character_error_rate(reference, transcript).rate == 0
