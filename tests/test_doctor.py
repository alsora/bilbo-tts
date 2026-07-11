from __future__ import annotations

import ctypes.util
import platform
import shutil
import sys
from pathlib import Path

import pytest

from bilbo_tts import doctor


def test_collect_environment_reports_project_managed_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment_root = tmp_path / ".pixi/envs/default"
    bin_directory = environment_root / "bin"
    executable_paths = {
        "pixi": tmp_path / ".tools/bin/pixi",
        "ffmpeg": bin_directory / "ffmpeg",
        "pandoc": bin_directory / "pandoc",
    }
    monkeypatch.setattr(sys, "executable", str(bin_directory / "python"))
    monkeypatch.setattr(
        shutil,
        "which",
        lambda command: str(executable_paths[command]) if command in executable_paths else None,
    )
    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: "libsndfile.dylib")
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "release", lambda: "23.5.0")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(doctor, "_module_available", lambda module: module == "mlx")

    report = doctor.collect_environment(
        {
            "PIXI_PROJECT_ROOT": str(tmp_path),
            "PIXI_ENVIRONMENT_NAME": "default",
        }
    )

    assert report["healthy"] is True
    assert report["environment"]["python_managed"] is True
    assert report["platform"]["apple_silicon"] is True
    assert report["acceleration"] == {
        "mlx_installed": True,
    }
    assert report["caches"]["models"] == str(tmp_path / "work/cache/models")


def test_collect_environment_rejects_system_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "release", lambda: "23.5.0")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(doctor, "_module_available", lambda _module: False)

    report = doctor.collect_environment({"PIXI_PROJECT_ROOT": str(tmp_path)})

    assert report["healthy"] is False
    assert report["environment"]["python_managed"] is False
