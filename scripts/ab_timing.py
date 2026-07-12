"""Run reproducible, counterbalanced TTS timing comparisons.

This is measurement tooling, not a pipeline stage. ``compare`` runs one
candidate per fresh subprocess so model state and unified memory cannot leak
between passes. It appends machine-readable JSONL records, excludes warmup
from sample timings, and optionally saves every WAV under a pass-specific
name. ``summarize`` reports paired same-text wall-time and RTF changes.

Use ``profile`` separately when collecting Python and MPS traces: profiling
changes execution timing and must not be mixed with benchmark evidence.

See performance.md for the complete measurement procedure.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bilbo_tts.benchmarking import (
    DEFAULT_BOOTSTRAP_RESAMPLES,
    SCHEMA_VERSION,
    JsonRecord,
    decode_record,
    load_records,
    render_summary,
)
from bilbo_tts.qualification.audio import pcm_wav_bytes
from bilbo_tts.qualification.candidates import candidate_path, load_tts_candidate
from bilbo_tts.qualification.corpus import default_corpus_path, load_corpus
from bilbo_tts.serialization import canonical_sha256, sha256_bytes
from bilbo_tts.tts import TtsRequest
from bilbo_tts.tts.factory import create_tts_engine

WARMUP_TEXT = "Breve riscaldamento del modello."
RECORD_PREFIX = "BILBO_TIMING "


def main() -> None:
    parser = _parser()
    arguments = parser.parse_args()
    if arguments.command == "compare":
        _compare(arguments, parser)
    elif arguments.command == "summarize":
        _summarize_command(arguments, parser)
    elif arguments.command == "profile":
        _profile(arguments, parser)
    elif arguments.command == "_run-pass":
        _run_pass(arguments, parser)
    else:
        parser.error("a command is required")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(
        dest="command",
        metavar="{compare,summarize,profile}",
    )

    compare = subparsers.add_parser("compare", help="run one counterbalanced A/B session")
    compare.add_argument("baseline", help="baseline candidate name")
    compare.add_argument("variant", help="variant candidate name")
    compare.add_argument("excerpts", help="comma-separated corpus excerpt identifiers")
    compare.add_argument(
        "--order",
        choices=("ABBA", "BAAB"),
        required=True,
        help="counterbalanced pass order; alternate the starting candidate across sessions",
    )
    compare.add_argument(
        "--output",
        type=Path,
        required=True,
        help="JSONL evidence file; independent sessions are appended",
    )
    compare.add_argument(
        "--session-id",
        default=None,
        help="stable identifier for this thermal session (generated when omitted)",
    )
    compare.add_argument(
        "--cooldown-seconds",
        type=int,
        default=0,
        help="fallback delay between passes; prefer observed thermal stability",
    )
    _add_common_arguments(compare, include_save_dir=True)

    summarize = subparsers.add_parser(
        "summarize",
        help="summarize paired samples from one JSONL evidence file",
    )
    summarize.add_argument("results", type=Path)
    summarize.add_argument(
        "--bootstrap-resamples",
        type=int,
        default=DEFAULT_BOOTSTRAP_RESAMPLES,
    )

    profile = subparsers.add_parser(
        "profile",
        help="profile one warmed candidate/excerpt outside benchmark runs",
    )
    profile.add_argument("candidate")
    profile.add_argument("excerpt")
    profile.add_argument(
        "--python-profile",
        type=Path,
        required=True,
        help="destination for cProfile data",
    )
    profile.add_argument(
        "--mps-signposts",
        action="store_true",
        help="emit MPS OS Signposts for an Instruments or log capture",
    )
    profile.add_argument(
        "--wait-until-completed",
        action="store_true",
        help="synchronize every MPS dispatch for trace clarity; materially changes timing",
    )
    _add_common_arguments(profile, include_save_dir=True)

    run_pass = subparsers.add_parser("_run-pass")
    run_pass.add_argument("candidate")
    run_pass.add_argument("excerpts")
    run_pass.add_argument("--session-id", required=True)
    run_pass.add_argument("--pass-index", type=int, required=True)
    run_pass.add_argument("--order", choices=("ABBA", "BAAB"), required=True)
    _add_common_arguments(run_pass, include_save_dir=True)
    return parser


def _add_common_arguments(parser: argparse.ArgumentParser, *, include_save_dir: bool) -> None:
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="repository root containing config/qualification/",
    )
    if include_save_dir:
        parser.add_argument(
            "--save-dir",
            type=Path,
            default=None,
            help="optional root receiving pass-specific WAVs outside timed regions",
        )


def _compare(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if arguments.baseline == arguments.variant:
        parser.error("baseline and variant candidates must differ")
    if arguments.cooldown_seconds < 0:
        parser.error("--cooldown-seconds must be zero or greater")
    excerpts = _parse_excerpts(arguments.excerpts, parser)
    project_root = arguments.project_root.expanduser().resolve()
    _load_selected_corpus(project_root, excerpts, parser)
    for name in (arguments.baseline, arguments.variant):
        load_tts_candidate(candidate_path(project_root, name))

    session_id = arguments.session_id or _new_session_id()
    output = arguments.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    _validate_evidence_target(
        output,
        baseline=arguments.baseline,
        variant=arguments.variant,
        session_id=session_id,
        parser=parser,
    )
    session_record: JsonRecord = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "session",
        "session_id": session_id,
        "started_at": _utc_now(),
        "baseline": arguments.baseline,
        "variant": arguments.variant,
        "order": arguments.order,
        "excerpts": list(excerpts),
        "corpus_sha256": sha256_bytes(default_corpus_path(project_root).read_bytes()),
        "script_sha256": _file_sha256(Path(__file__)),
        "host": _host_metadata(),
        "repository": _repository_metadata(project_root),
    }
    _append_record(output, session_record)
    print(f"Timing session {session_id} -> {output}", flush=True)

    candidates = {
        "A": arguments.baseline,
        "B": arguments.variant,
    }
    for pass_index, label in enumerate(arguments.order, start=1):
        if pass_index > 1 and arguments.cooldown_seconds:
            print(
                f"Cooling down for {arguments.cooldown_seconds} seconds before pass {pass_index}.",
                flush=True,
            )
            time.sleep(arguments.cooldown_seconds)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "_run-pass",
            candidates[label],
            ",".join(excerpts),
            "--session-id",
            session_id,
            "--pass-index",
            str(pass_index),
            "--order",
            arguments.order,
            "--project-root",
            str(project_root),
        ]
        if arguments.save_dir is not None:
            command.extend(["--save-dir", str(arguments.save_dir.expanduser().resolve())])
        _run_subprocess_pass(command, output, session_id, pass_index, candidates[label])

    print(render_summary(load_records(output)), flush=True)


def _run_subprocess_pass(
    command: list[str],
    output: Path,
    session_id: str,
    pass_index: int,
    candidate: str,
) -> None:
    process = subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    for line in process.stdout:
        if line.startswith(RECORD_PREFIX):
            record = decode_record(line.removeprefix(RECORD_PREFIX), output)
            _append_record(output, record)
        else:
            print(line, end="", flush=True)
    return_code = process.wait()
    if return_code:
        _append_record(
            output,
            {
                "schema_version": SCHEMA_VERSION,
                "record_type": "pass_failed",
                "session_id": session_id,
                "pass_index": pass_index,
                "candidate": candidate,
                "return_code": return_code,
                "failed_at": _utc_now(),
            },
        )
        raise SystemExit(f"timing pass {pass_index} failed with exit code {return_code}")


def _run_pass(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    excerpts = _parse_excerpts(arguments.excerpts, parser)
    project_root = arguments.project_root.expanduser().resolve()
    selected = _load_selected_corpus(project_root, excerpts, parser)
    config = load_tts_candidate(candidate_path(project_root, arguments.candidate))
    engine = create_tts_engine(config, project_root)
    thermal_before = _thermal_snapshot()
    warmup = TtsRequest(spoken_text=WARMUP_TEXT, voice=config.voice, settings=config.settings)
    warmup_started = time.perf_counter()
    engine.synthesize(warmup)
    _synchronize_mps(config.backend)
    warmup_seconds = time.perf_counter() - warmup_started

    _emit_record(
        {
            "schema_version": SCHEMA_VERSION,
            "record_type": "pass_started",
            "session_id": arguments.session_id,
            "pass_index": arguments.pass_index,
            "order": arguments.order,
            "candidate": arguments.candidate,
            "candidate_sha256": canonical_sha256(config),
            "model_revision": config.model.revision,
            "code_revision": config.code_revision,
            "packages": _package_versions(),
            "thermal_before": thermal_before,
            "warmup_including_lazy_load_seconds": warmup_seconds,
            "started_at": _utc_now(),
        }
    )

    save_dir = None
    if arguments.save_dir is not None:
        save_dir = (
            arguments.save_dir.expanduser().resolve()
            / arguments.session_id
            / f"pass-{arguments.pass_index:02d}-{arguments.candidate}"
        )
        save_dir.mkdir(parents=True, exist_ok=True)
    for excerpt_id in excerpts:
        excerpt = selected[excerpt_id]
        request = TtsRequest(
            spoken_text=excerpt.spoken_text,
            voice=config.voice,
            settings=config.settings,
        )
        _synchronize_mps(config.backend)
        started = time.perf_counter()
        result = engine.synthesize(request)
        _synchronize_mps(config.backend)
        elapsed = time.perf_counter() - started
        record: JsonRecord = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "sample",
            "session_id": arguments.session_id,
            "pass_index": arguments.pass_index,
            "candidate": arguments.candidate,
            "excerpt": excerpt_id,
            "generation_seconds": elapsed,
            "audio_seconds": result.duration_seconds,
            "rtf": elapsed / result.duration_seconds,
        }
        if save_dir is not None:
            wav_path = save_dir / f"{excerpt_id}.wav"
            wav_path.write_bytes(pcm_wav_bytes(result))
            record["wav_path"] = str(wav_path)
        _emit_record(record)

    _emit_record(
        {
            "schema_version": SCHEMA_VERSION,
            "record_type": "pass_completed",
            "session_id": arguments.session_id,
            "pass_index": arguments.pass_index,
            "candidate": arguments.candidate,
            "peak_rss_bytes": _process_peak_rss_bytes(),
            "thermal_after": _thermal_snapshot(),
            "completed_at": _utc_now(),
        }
    )


def _profile(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if arguments.wait_until_completed and not arguments.mps_signposts:
        parser.error("--wait-until-completed requires --mps-signposts")
    project_root = arguments.project_root.expanduser().resolve()
    selected = _load_selected_corpus(project_root, (arguments.excerpt,), parser)
    config = load_tts_candidate(candidate_path(project_root, arguments.candidate))
    engine = create_tts_engine(config, project_root)
    warmup = TtsRequest(spoken_text=WARMUP_TEXT, voice=config.voice, settings=config.settings)
    engine.synthesize(warmup)
    _synchronize_mps(config.backend)
    excerpt = selected[arguments.excerpt]
    request = TtsRequest(
        spoken_text=excerpt.spoken_text,
        voice=config.voice,
        settings=config.settings,
    )

    python_profile = arguments.python_profile.expanduser().resolve()
    python_profile.parent.mkdir(parents=True, exist_ok=True)
    profiler = cProfile.Profile()
    mps_context = _mps_profile_context(
        config.backend,
        enabled=arguments.mps_signposts,
        wait_until_completed=arguments.wait_until_completed,
    )
    _synchronize_mps(config.backend)
    started = time.perf_counter()
    profiler.enable()
    with mps_context:
        result = engine.synthesize(request)
    profiler.disable()
    _synchronize_mps(config.backend)
    elapsed = time.perf_counter() - started
    profiler.dump_stats(python_profile)

    record: JsonRecord = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "profile",
        "candidate": arguments.candidate,
        "excerpt": arguments.excerpt,
        "generation_seconds": elapsed,
        "audio_seconds": result.duration_seconds,
        "rtf": elapsed / result.duration_seconds,
        "python_profile": str(python_profile),
        "mps_signposts": arguments.mps_signposts,
        "wait_until_completed": arguments.wait_until_completed,
    }
    if arguments.save_dir is not None:
        save_dir = arguments.save_dir.expanduser().resolve()
        save_dir.mkdir(parents=True, exist_ok=True)
        wav_path = save_dir / f"profile-{arguments.candidate}-{arguments.excerpt}.wav"
        wav_path.write_bytes(pcm_wav_bytes(result))
        record["wav_path"] = str(wav_path)
    print(json.dumps(record, sort_keys=True), flush=True)


def _mps_profile_context(backend: str, *, enabled: bool, wait_until_completed: bool) -> Any:
    if not enabled:
        from contextlib import nullcontext

        return nullcontext()
    if backend != "pytorch-mps":
        raise ValueError("--mps-signposts requires a pytorch-mps candidate")
    import torch

    return torch.mps.profiler.profile(
        mode="interval,event",
        wait_until_completed=wait_until_completed,
    )


def _synchronize_mps(backend: str) -> None:
    if backend != "pytorch-mps":
        return
    import torch

    torch.mps.synchronize()


def _summarize_command(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if arguments.bootstrap_resamples <= 0:
        parser.error("--bootstrap-resamples must be positive")
    try:
        records = load_records(arguments.results)
        print(
            render_summary(records, bootstrap_resamples=arguments.bootstrap_resamples),
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))


def _parse_excerpts(value: str, parser: argparse.ArgumentParser) -> tuple[str, ...]:
    excerpts = tuple(part.strip() for part in value.split(",") if part.strip())
    if not excerpts:
        parser.error("at least one excerpt is required")
    if len(excerpts) != len(set(excerpts)):
        parser.error("excerpt identifiers must be unique")
    return excerpts


def _validate_evidence_target(
    output: Path,
    *,
    baseline: str,
    variant: str,
    session_id: str,
    parser: argparse.ArgumentParser,
) -> None:
    if not output.exists() or output.stat().st_size == 0:
        return
    try:
        records = load_records(output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    sessions = [record for record in records if record.get("record_type") == "session"]
    if any(str(record.get("session_id")) == session_id for record in sessions):
        parser.error(f"session identifier already exists in {output}: {session_id}")
    pairs = {(str(record.get("baseline")), str(record.get("variant"))) for record in sessions}
    if pairs and pairs != {(baseline, variant)}:
        parser.error(
            f"evidence file contains different candidate pairs: {sorted(pairs)}; "
            "use a separate output file"
        )


def _load_selected_corpus(
    project_root: Path,
    excerpts: tuple[str, ...],
    parser: argparse.ArgumentParser,
) -> dict[str, Any]:
    corpus = {
        excerpt.excerpt_id: excerpt
        for excerpt in load_corpus(default_corpus_path(project_root)).excerpts
    }
    unknown = [name for name in excerpts if name not in corpus]
    if unknown:
        parser.error(f"unknown corpus excerpts: {', '.join(unknown)}")
    return {name: corpus[name] for name in excerpts}


def _append_record(path: Path, record: JsonRecord) -> None:
    with path.open("a", encoding="utf-8") as destination:
        destination.write(json.dumps(record, allow_nan=False, sort_keys=True) + "\n")
        destination.flush()
        os.fsync(destination.fileno())


def _emit_record(record: JsonRecord) -> None:
    print(RECORD_PREFIX + json.dumps(record, allow_nan=False, sort_keys=True), flush=True)


def _new_session_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _host_metadata() -> JsonRecord:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "macos": platform.mac_ver()[0] or None,
        "python": platform.python_version(),
    }


def _repository_metadata(project_root: Path) -> JsonRecord:
    def git(*arguments: str) -> str | None:
        try:
            completed = subprocess.run(  # noqa: S603
                ["git", *arguments],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return completed.stdout.strip()

    return {
        "head": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
    }


def _package_versions() -> JsonRecord:
    versions: JsonRecord = {}
    for distribution in ("chatterbox-tts", "torch", "transformers", "resemble-perth"):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions


def _thermal_snapshot() -> JsonRecord | None:
    if sys.platform != "darwin":
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            ["pmset", "-g", "therm"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return {
        "return_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _process_peak_rss_bytes() -> int | None:
    if sys.platform != "darwin":
        return None
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if peak > 0 else None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
