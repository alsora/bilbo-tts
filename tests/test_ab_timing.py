from __future__ import annotations

import json
from pathlib import Path

import pytest

from bilbo_tts.benchmarking import (
    SCHEMA_VERSION,
    bootstrap_median_interval,
    load_records,
    render_summary,
)


def session(session_id: str, order: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "session",
        "session_id": session_id,
        "baseline": "baseline",
        "variant": "variant",
        "order": order,
        "excerpts": ["prose", "numbers"],
    }


def sample(
    session_id: str,
    candidate: str,
    excerpt: str,
    generation_seconds: float,
    rtf: float,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "sample",
        "session_id": session_id,
        "candidate": candidate,
        "excerpt": excerpt,
        "generation_seconds": generation_seconds,
        "audio_seconds": generation_seconds / rtf,
        "rtf": rtf,
    }


def completed(session_id: str, pass_index: int, candidate: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "pass_completed",
        "session_id": session_id,
        "pass_index": pass_index,
        "candidate": candidate,
    }


def test_summary_pairs_candidates_within_each_session_and_excerpt() -> None:
    records = [
        session("cold-a", "ABBA"),
        sample("cold-a", "baseline", "prose", 10.0, 5.0),
        sample("cold-a", "variant", "prose", 8.0, 4.0),
        sample("cold-a", "variant", "prose", 7.0, 3.5),
        sample("cold-a", "baseline", "prose", 12.0, 6.0),
        sample("cold-a", "baseline", "numbers", 20.0, 5.0),
        sample("cold-a", "variant", "numbers", 15.0, 4.0),
        sample("cold-a", "variant", "numbers", 15.0, 4.0),
        sample("cold-a", "baseline", "numbers", 20.0, 5.0),
        completed("cold-a", 1, "baseline"),
        completed("cold-a", 2, "variant"),
        completed("cold-a", 3, "variant"),
        completed("cold-a", 4, "baseline"),
        session("cold-b", "BAAB"),
        sample("cold-b", "variant", "prose", 9.0, 4.5),
        sample("cold-b", "baseline", "prose", 12.0, 6.0),
        sample("cold-b", "baseline", "prose", 12.0, 6.0),
        sample("cold-b", "variant", "prose", 9.0, 4.5),
        sample("cold-b", "baseline", "numbers", 24.0, 6.0),
        sample("cold-b", "variant", "numbers", 18.0, 4.5),
        sample("cold-b", "variant", "numbers", 18.0, 4.5),
        sample("cold-b", "baseline", "numbers", 24.0, 6.0),
        completed("cold-b", 1, "variant"),
        completed("cold-b", 2, "baseline"),
        completed("cold-b", 3, "baseline"),
        completed("cold-b", 4, "variant"),
    ]

    summary = render_summary(records, bootstrap_resamples=500)

    assert "- Complete sessions: 2 of 2" in summary
    assert "- Paired thermal-session observations: 2" in summary
    assert "`baseline` median sample: 16.000 s wall, RTF 5.750" in summary
    assert "`variant` median sample: 12.000 s wall, RTF 4.250" in summary
    assert "- Same-text wall-time reduction: 26.2% median;" in summary
    assert "- RTF reduction: 24.6% median;" in summary


def test_summary_rejects_incomplete_sessions() -> None:
    records = [
        session("partial", "ABBA"),
        sample("partial", "baseline", "prose", 10.0, 5.0),
        sample("partial", "variant", "prose", 8.0, 4.0),
    ]

    with pytest.raises(ValueError, match="no complete paired sessions"):
        render_summary(records, bootstrap_resamples=100)


def test_bootstrap_interval_is_deterministic_and_requires_multiple_values() -> None:
    assert bootstrap_median_interval([0.2]) is None
    assert bootstrap_median_interval([0.1, 0.2, 0.3], resamples=500) == (0.1, 0.3)
    with pytest.raises(ValueError, match="resamples must be positive"):
        bootstrap_median_interval([0.1, 0.2], resamples=0)


def test_load_records_rejects_non_versioned_json(tmp_path: Path) -> None:
    valid = session("valid", "ABBA")
    evidence = tmp_path / "timing.jsonl"
    evidence.write_text(
        json.dumps(valid) + "\n" + json.dumps({"record_type": "sample"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"invalid timing record.*:2"):
        load_records(evidence)
