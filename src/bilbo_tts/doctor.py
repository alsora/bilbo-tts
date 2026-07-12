"""Inspect the local execution environment without loading model runtimes."""

from __future__ import annotations

import ctypes.util
import importlib.util
import os
import platform
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict


class EnvironmentReport(TypedDict):
    """Machine-readable result returned by the environment doctor."""

    healthy: bool
    platform: dict[str, str | bool]
    environment: dict[str, str | bool | None]
    tools: dict[str, str | None]
    caches: dict[str, str]
    acceleration: dict[str, bool]


def _project_root(environment: Mapping[str, str]) -> Path:
    configured_root = environment.get("PIXI_PROJECT_ROOT")
    return Path(configured_root or Path.cwd()).expanduser().resolve()


def _managed_path(path: str | None, project_root: Path) -> bool:
    if path is None:
        return False
    resolved_path = Path(path).expanduser().resolve()
    return any(
        resolved_path.is_relative_to(root)
        for root in (project_root / ".pixi", project_root / ".tools")
    )


def _module_available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def collect_environment(
    environment: Mapping[str, str] | None = None,
) -> EnvironmentReport:
    """Collect paths and capabilities without importing heavyweight ML packages."""

    active_environment = environment if environment is not None else os.environ
    project_root = _project_root(active_environment)
    project_pixi = project_root / ".tools/bin/pixi"
    tools = {
        "python": sys.executable,
        "pixi": shutil.which("pixi") or (str(project_pixi) if project_pixi.is_file() else None),
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "pandoc": shutil.which("pandoc"),
        "libsndfile": ctypes.util.find_library("sndfile"),
    }
    required_tools = ("python", "ffmpeg", "ffprobe", "pandoc")
    healthy = all(_managed_path(tools[name], project_root) for name in required_tools)
    is_apple_silicon = platform.system() == "Darwin" and platform.machine() == "arm64"

    return {
        "healthy": healthy,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "apple_silicon": is_apple_silicon,
        },
        "environment": {
            "project_root": str(project_root),
            "pixi_environment": active_environment.get("PIXI_ENVIRONMENT_NAME"),
            "python_prefix": sys.prefix,
            "python_managed": _managed_path(sys.executable, project_root),
        },
        "tools": tools,
        "caches": {
            "huggingface": active_environment.get(
                "HF_HOME", str(project_root / "work/cache/huggingface")
            ),
            "xdg": active_environment.get("XDG_CACHE_HOME", str(project_root / "work/cache/xdg")),
            "models": active_environment.get(
                "BILBO_MODEL_CACHE", str(project_root / "work/cache/models")
            ),
        },
        "acceleration": {
            "mlx_installed": _module_available("mlx"),
        },
    }
