"""Deterministic parsing and statistics for TTS benchmark evidence."""

from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

SCHEMA_VERSION = "ab-timing/v2"
DEFAULT_BOOTSTRAP_RESAMPLES = 10_000

JsonRecord = dict[str, object]


def load_records(path: Path) -> list[JsonRecord]:
    """Load and minimally validate timing records from one JSONL file."""

    records: list[JsonRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        records.append(decode_record(line, path, line_number=line_number))
    if not records:
        raise ValueError(f"timing evidence file is empty: {path}")
    return records


def decode_record(value: str, path: Path, *, line_number: int | None = None) -> JsonRecord:
    """Decode one versioned JSON timing record."""

    location = f"{path}:{line_number}" if line_number is not None else str(path)
    try:
        record = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid timing JSON at {location}: {error}") from error
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"invalid timing record at {location}")
    return record


def render_summary(
    records: list[JsonRecord],
    *,
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
) -> str:
    """Render paired wall-time and RTF changes across complete sessions."""

    sessions = {
        str(record["session_id"]): record
        for record in records
        if record.get("record_type") == "session"
    }
    samples: dict[tuple[str, str, str], list[JsonRecord]] = defaultdict(list)
    for record in records:
        if record.get("record_type") != "sample":
            continue
        key = (
            str(record["session_id"]),
            str(record["excerpt"]),
            str(record["candidate"]),
        )
        samples[key].append(record)
    completed_passes: dict[str, list[JsonRecord]] = defaultdict(list)
    for record in records:
        if record.get("record_type") == "pass_completed":
            completed_passes[str(record["session_id"])].append(record)

    session_wall_reductions: list[float] = []
    session_rtf_reductions: list[float] = []
    candidate_wall: dict[str, list[float]] = defaultdict(list)
    candidate_rtf: dict[str, list[float]] = defaultdict(list)
    complete_sessions: set[str] = set()
    for session_id, session in sessions.items():
        baseline = str(session["baseline"])
        variant = str(session["variant"])
        excerpts = session.get("excerpts")
        if not isinstance(excerpts, list):
            raise ValueError(f"session {session_id!r} has invalid excerpts")
        order = session.get("order")
        if order not in {"ABBA", "BAAB"}:
            raise ValueError(f"session {session_id!r} has invalid order")
        candidate_by_label = {"A": baseline, "B": variant}
        expected_passes = [
            (index, candidate_by_label[label]) for index, label in enumerate(order, start=1)
        ]
        actual_passes = sorted(
            _pass_identity(record) for record in completed_passes.get(session_id, [])
        )
        session_complete = actual_passes == expected_passes
        for excerpt_value in excerpts:
            excerpt = str(excerpt_value)
            if (
                len(samples.get((session_id, excerpt, baseline), [])) != 2
                or len(samples.get((session_id, excerpt, variant), [])) != 2
            ):
                session_complete = False
        if not session_complete:
            continue
        baseline_wall_total = 0.0
        variant_wall_total = 0.0
        baseline_audio_total = 0.0
        variant_audio_total = 0.0
        for excerpt_value in excerpts:
            excerpt = str(excerpt_value)
            baseline_samples = samples[(session_id, excerpt, baseline)]
            variant_samples = samples[(session_id, excerpt, variant)]
            baseline_wall = statistics.median(_numbers(baseline_samples, "generation_seconds"))
            variant_wall = statistics.median(_numbers(variant_samples, "generation_seconds"))
            baseline_rtf = statistics.median(_numbers(baseline_samples, "rtf"))
            variant_rtf = statistics.median(_numbers(variant_samples, "rtf"))
            baseline_audio = statistics.median(_numbers(baseline_samples, "audio_seconds"))
            variant_audio = statistics.median(_numbers(variant_samples, "audio_seconds"))
            candidate_wall[baseline].append(baseline_wall)
            candidate_wall[variant].append(variant_wall)
            candidate_rtf[baseline].append(baseline_rtf)
            candidate_rtf[variant].append(variant_rtf)
            baseline_wall_total += baseline_wall
            variant_wall_total += variant_wall
            baseline_audio_total += baseline_audio
            variant_audio_total += variant_audio
        session_wall_reductions.append(1.0 - variant_wall_total / baseline_wall_total)
        session_rtf_reductions.append(
            1.0
            - (variant_wall_total / variant_audio_total)
            / (baseline_wall_total / baseline_audio_total)
        )
        complete_sessions.add(session_id)
    if not session_wall_reductions:
        raise ValueError("timing evidence contains no complete paired sessions")

    lines = [
        "# A/B timing summary",
        "",
        f"- Complete sessions: {len(complete_sessions)} of {len(sessions)}",
        f"- Paired thermal-session observations: {len(session_wall_reductions)}",
    ]
    for candidate in sorted(candidate_wall):
        lines.append(
            f"- `{candidate}` median sample: "
            f"{statistics.median(candidate_wall[candidate]):.3f} s wall, "
            f"RTF {statistics.median(candidate_rtf[candidate]):.3f}"
        )
    lines.extend(
        [
            _reduction_line(
                "Same-text wall-time reduction",
                session_wall_reductions,
                bootstrap_resamples,
            ),
            _reduction_line("RTF reduction", session_rtf_reductions, bootstrap_resamples),
        ]
    )
    return "\n".join(lines)


def bootstrap_median_interval(
    values: list[float],
    *,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = 0,
) -> tuple[float, float] | None:
    """Return a deterministic percentile-bootstrap interval for the median."""

    if len(values) < 2:
        return None
    if resamples <= 0:
        raise ValueError("bootstrap resamples must be positive")
    generator = random.Random(seed)
    medians = sorted(
        statistics.median(generator.choices(values, k=len(values))) for _ in range(resamples)
    )
    lower = medians[round(0.025 * (len(medians) - 1))]
    upper = medians[round(0.975 * (len(medians) - 1))]
    return lower, upper


def _numbers(records: list[JsonRecord], field: str) -> list[float]:
    values: list[float] = []
    for record in records:
        value = record.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"sample record has invalid {field}")
        number = float(value)
        if number <= 0:
            raise ValueError(f"sample record has non-positive {field}")
        values.append(number)
    return values


def _pass_identity(record: JsonRecord) -> tuple[int, str]:
    pass_index = record.get("pass_index")
    candidate = record.get("candidate")
    if (
        isinstance(pass_index, bool)
        or not isinstance(pass_index, int)
        or not isinstance(candidate, str)
    ):
        raise ValueError("completed pass has invalid identity")
    return pass_index, candidate


def _reduction_line(label: str, values: list[float], resamples: int) -> str:
    median = statistics.median(values)
    interval = bootstrap_median_interval(values, resamples=resamples)
    if interval is None:
        return f"- {label}: {median:.1%} median; interval unavailable"
    return (
        f"- {label}: {median:.1%} median; bootstrap 95% CI {interval[0]:.1%} to {interval[1]:.1%}"
    )
