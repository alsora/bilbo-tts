from __future__ import annotations

import math
import wave
from io import BytesIO

import pytest

from bilbo_tts.config import VerificationThresholds
from bilbo_tts.models import ReviewStatus, VerificationHeuristics
from bilbo_tts.verification import _audio_heuristics, _classify, _repetition_excess


def _wav(samples: list[int], *, sample_rate_hz: int = 1_000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate_hz)
        output.writeframes(
            b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples)
        )
    return buffer.getvalue()


def _heuristics(**updates: float | int) -> VerificationHeuristics:
    values: dict[str, float | int] = {
        "missing_prefix_words": 0,
        "missing_suffix_words": 0,
        "repeated_ngram_count": 0,
        "silence_ratio": 0.1,
        "clipped_sample_ratio": 0,
        "peak_dbfs": -3,
    }
    values.update(updates)
    return VerificationHeuristics.model_validate(values)


def test_audio_heuristics_detect_silence_and_clipping() -> None:
    silent = _audio_heuristics(_wav([0] * 100))
    clipped = _audio_heuristics(_wav([32767, -32768] * 50))

    assert silent.silence_ratio == 1
    assert silent.peak_dbfs == -120
    assert clipped.clipped_sample_ratio == 1
    assert clipped.peak_dbfs == pytest.approx(0, abs=0.001)


@pytest.mark.parametrize(
    ("updates", "speaking_rate", "reason"),
    [
        ({"missing_suffix_words": 2}, 140, "missing-suffix"),
        ({"missing_prefix_words": 2}, 140, "missing-prefix"),
        ({"repeated_ngram_count": 1}, 140, "repeated-ngram"),
        ({"silence_ratio": 0.99}, 140, "excessive-silence"),
        ({"clipped_sample_ratio": 0.1}, 140, "clipping"),
        ({}, 20, "speaking-rate-low"),
        ({}, 400, "speaking-rate-high"),
    ],
)
def test_retryable_audio_defects_become_review_after_bound(
    updates: dict[str, float | int],
    speaking_rate: float,
    reason: str,
) -> None:
    thresholds = VerificationThresholds()
    reasons, first = _classify(
        transcript="testo valido",
        wer=0,
        cer=0,
        speaking_rate=speaking_rate,
        heuristics=_heuristics(**updates),
        thresholds=thresholds,
        attempt_number=0,
        max_auto_retries=1,
        word_count=12,
    )
    exhausted_reasons, exhausted = _classify(
        transcript="testo valido",
        wer=0,
        cer=0,
        speaking_rate=speaking_rate,
        heuristics=_heuristics(**updates),
        thresholds=thresholds,
        attempt_number=1,
        max_auto_retries=1,
        word_count=12,
    )

    assert reason in reasons
    assert exhausted_reasons == reasons
    assert first == ReviewStatus.RETRYABLE
    assert exhausted == ReviewStatus.REVIEW


def test_asr_metric_failures_require_review_without_blind_retry() -> None:
    reasons, status = _classify(
        transcript="testo diverso",
        wer=0.8,
        cer=0.9,
        speaking_rate=140,
        heuristics=_heuristics(),
        thresholds=VerificationThresholds(),
        attempt_number=0,
        max_auto_retries=2,
        word_count=12,
    )

    assert reasons == ("wer-high", "cer-high")
    assert status == ReviewStatus.REVIEW


def test_repetition_excess_ignores_repetition_present_in_reference() -> None:
    assert _repetition_excess("molto molto utile", "molto molto utile") == 0
    assert _repetition_excess("molto utile", "molto molto molto utile") == 2


def test_speed_changed_duration_changes_speaking_rate() -> None:
    word_count = 12
    normal_duration_seconds = 6
    altered_duration_seconds = 1.5

    normal_rate = word_count * 60 / normal_duration_seconds
    altered_rate = word_count * 60 / altered_duration_seconds

    assert math.isclose(normal_rate, 120)
    reasons, status = _classify(
        transcript=" ".join(["parola"] * word_count),
        wer=0,
        cer=0,
        speaking_rate=altered_rate,
        heuristics=_heuristics(),
        thresholds=VerificationThresholds(),
        attempt_number=0,
        max_auto_retries=2,
        word_count=word_count,
    )
    assert reasons == ("speaking-rate-high",)
    assert status == ReviewStatus.RETRYABLE


def test_short_heading_is_not_classified_by_speaking_rate() -> None:
    reasons, status = _classify(
        transcript="introduzione",
        wer=0,
        cer=0,
        speaking_rate=48,
        heuristics=_heuristics(),
        thresholds=VerificationThresholds(),
        attempt_number=0,
        max_auto_retries=2,
        word_count=1,
    )

    assert reasons == ()
    assert status == ReviewStatus.ACCEPTED
