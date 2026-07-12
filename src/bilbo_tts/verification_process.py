"""Process-isolated coordination for ASR verification and TTS retries."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from bilbo_tts.qualification.candidates import CandidateConfigurationError
from bilbo_tts.stages import load_stage_context
from bilbo_tts.tts.factory import resolve_book_candidate
from bilbo_tts.verification import VerificationError, VerifySummary

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def run_verification_loop(
    config_path: Path,
    project_root: Path,
    *,
    chapter: str | None = None,
    command_runner: CommandRunner = subprocess.run,
    pixi_executable: Path | None = None,
) -> VerifySummary:
    """Alternate isolated ASR and TTS processes until verification settles."""

    context = load_stage_context(config_path, project_root)
    try:
        candidate = resolve_book_candidate(
            context.config.synthesis,
            context.workspace.project_root,
        )
    except CandidateConfigurationError as error:
        raise VerificationError(str(error)) from error
    pixi = pixi_executable or _resolve_pixi_executable()
    config_argument = _config_argument(config_path, context.workspace.project_root)
    common = [
        config_argument,
        "--project-root",
        str(context.workspace.project_root),
    ]
    if chapter is not None:
        common.extend(["--chapter", chapter])
    maximum_passes = context.config.verification.max_auto_retries + 2
    for _ in range(maximum_passes):
        verify_command = [
            str(pixi),
            "run",
            "-e",
            "asr",
            "bilbo",
            "verify-pass",
            *common,
        ]
        verified = _run_json_command(command_runner, verify_command, "ASR verification")
        try:
            summary = VerifySummary.model_validate(verified)
        except Exception as error:
            raise VerificationError(
                f"ASR verification returned an invalid summary: {error}"
            ) from error
        if summary.status != "retryable":
            return summary
        synthesis_command = [
            str(pixi),
            "run",
            "-e",
            _tts_environment(candidate.engine),
            "bilbo",
            "synthesize",
            config_argument,
            "--project-root",
            str(context.workspace.project_root),
            "--verification-retry",
        ]
        if chapter is not None:
            synthesis_command.extend(["--chapter", chapter])
        _run_json_command(command_runner, synthesis_command, "verification-driven synthesis")
    raise VerificationError(
        "verification retry loop exceeded its configured bound without settling"
    )


def _run_json_command(
    runner: CommandRunner,
    command: Sequence[str],
    label: str,
) -> dict[str, Any]:
    completed = runner(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic output"
        raise VerificationError(f"{label} process failed: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise VerificationError(f"{label} process returned invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise VerificationError(f"{label} process returned a non-object JSON summary")
    return payload


def _resolve_pixi_executable() -> Path:
    configured = os.environ.get("PIXI_EXE")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate.resolve()
    discovered = shutil.which("pixi")
    if discovered:
        return Path(discovered).resolve()
    repository_local = Path(__file__).parents[2] / ".tools" / "bin" / "pixi"
    if repository_local.is_file():
        return repository_local.resolve()
    raise VerificationError(
        "cannot locate Pixi for isolated verification; set PIXI_EXE or add pixi to PATH"
    )


def _config_argument(config_path: Path, project_root: Path) -> str:
    candidate = config_path.expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return str(candidate.resolve())


def _tts_environment(engine: str) -> str:
    if engine in {"kokoro", "chatterbox"}:
        return engine
    if engine == "fake":
        return "default"
    raise VerificationError(f"no isolated Pixi environment is configured for TTS engine {engine!r}")
