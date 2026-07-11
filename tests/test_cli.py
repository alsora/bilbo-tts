from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from bilbo_tts import cli
from bilbo_tts.doctor import EnvironmentReport

runner = CliRunner()


def _report(*, healthy: bool = True) -> EnvironmentReport:
    return {
        "healthy": healthy,
        "platform": {
            "system": "Darwin",
            "release": "23.5.0",
            "machine": "arm64",
            "apple_silicon": True,
        },
        "environment": {
            "project_root": "/project",
            "pixi_environment": "default",
            "python_prefix": "/project/.pixi/envs/default",
            "python_managed": healthy,
        },
        "tools": {
            "python": "/project/.pixi/envs/default/bin/python",
            "pixi": "/project/.tools/bin/pixi",
            "ffmpeg": "/project/.pixi/envs/default/bin/ffmpeg",
            "pandoc": "/project/.pixi/envs/default/bin/pandoc",
            "libsndfile": "libsndfile.dylib",
        },
        "caches": {
            "huggingface": "/project/work/cache/huggingface",
            "xdg": "/project/work/cache/xdg",
            "models": "/project/work/cache/models",
        },
        "acceleration": {
            "mlx_installed": False,
        },
    }


def test_doctor_prints_readable_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "collect_environment", _report)

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == 0
    assert "Status: healthy" in result.stdout
    assert "ffmpeg: /project/.pixi/envs/default/bin/ffmpeg" in result.stdout
    assert "mlx_installed: False" in result.stdout


def test_doctor_prints_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "collect_environment", _report)

    result = runner.invoke(cli.app, ["doctor", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["healthy"] is True


def test_doctor_fails_for_unmanaged_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "collect_environment", lambda: _report(healthy=False))

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == 1
    assert "Status: unhealthy" in result.stdout


def test_root_command_shows_help() -> None:
    result = runner.invoke(cli.app)

    assert result.exit_code == 2
    assert "Build reproducible Italian audiobooks." in result.stdout
