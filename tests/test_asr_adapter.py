from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bilbo_tts.asr import (
    MODEL_ID,
    MODEL_REVISION,
    AsrError,
    MlxWhisperDependencies,
    MlxWhisperTranscriber,
    Transcriber,
)
from bilbo_tts.asr import mlx_whisper as mlx_whisper_adapter
from bilbo_tts.qualification.candidates import (
    AsrCandidateConfig,
    candidate_path,
    load_asr_candidate,
)

ROOT = Path(__file__).parents[1]


def config() -> AsrCandidateConfig:
    return load_asr_candidate(candidate_path(ROOT, "asr"))


def test_transcriber_is_lazy_resolves_pin_once_and_uses_exact_settings(
    tmp_path: Path,
) -> None:
    snapshot_calls: list[dict[str, object]] = []
    transcription_calls: list[tuple[str, dict[str, object]]] = []

    def snapshot_download(**kwargs: object) -> str:
        snapshot_calls.append(kwargs)
        return "/cache/pinned-whisper"

    def transcribe(path: str, **kwargs: object) -> object:
        transcription_calls.append((path, kwargs))
        return {"text": " Testo trascritto. "}

    transcriber = MlxWhisperTranscriber(
        config(),
        dependencies=MlxWhisperDependencies(snapshot_download, transcribe),
    )

    assert isinstance(transcriber, Transcriber)
    assert snapshot_calls == []
    assert transcription_calls == []

    first_wav = tmp_path / "first.wav"
    second_wav = tmp_path / "second.wav"
    assert transcriber.transcribe(first_wav) == " Testo trascritto. "
    assert transcriber.transcribe(second_wav) == " Testo trascritto. "

    assert snapshot_calls == [{"repo_id": MODEL_ID, "revision": MODEL_REVISION}]
    expected_settings = {
        "path_or_hf_repo": "/cache/pinned-whisper",
        "language": "it",
        "task": "transcribe",
        "temperature": 0.0,
        "fp16": True,
        "verbose": None,
        "word_timestamps": False,
    }
    assert transcription_calls == [
        (str(first_wav.resolve()), expected_settings),
        (str(second_wav.resolve()), expected_settings),
    ]
    assert all("initial_prompt" not in kwargs for _, kwargs in transcription_calls)


def test_prepare_is_lazy_and_never_transcribes() -> None:
    calls: list[str] = []

    def snapshot_download(**_kwargs: object) -> str:
        calls.append("snapshot")
        return "/cache/pinned-whisper"

    def transcribe(_path: str, **_kwargs: object) -> object:
        calls.append("transcribe")
        return {"text": ""}

    transcriber = MlxWhisperTranscriber(
        config(),
        dependencies=MlxWhisperDependencies(snapshot_download, transcribe),
    )

    transcriber.prepare()
    transcriber.prepare()

    assert calls == ["snapshot"]


@pytest.mark.parametrize(
    "change,message",
    [
        ({"model_id": "other/model"}, "pinned model"),
        ({"revision": "main"}, "pinned model"),
        ({"backend": "cpu"}, "Italian MLX config"),
        ({"language": "en"}, "Italian MLX config"),
    ],
)
def test_transcriber_rejects_non_exact_configuration(
    change: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(AsrError, match=message):
        MlxWhisperTranscriber(config().model_copy(update=change))


@pytest.mark.parametrize(
    "response,message",
    [
        ("not a mapping", "non-mapping"),
        ({}, "missing string field"),
        ({"text": None}, "missing string field"),
    ],
)
def test_transcriber_rejects_invalid_backend_results(
    tmp_path: Path,
    response: object,
    message: str,
) -> None:
    dependencies = MlxWhisperDependencies(
        lambda **_kwargs: "/cache/pinned-whisper",
        lambda _path, **_kwargs: response,
    )

    with pytest.raises(AsrError, match=message):
        MlxWhisperTranscriber(config(), dependencies=dependencies).transcribe(
            tmp_path / "audio.wav"
        )


def test_transcriber_reports_snapshot_failures_and_preserves_backend_failures(
    tmp_path: Path,
) -> None:
    def unavailable(**_kwargs: object) -> str:
        raise RuntimeError("offline")

    with pytest.raises(AsrError, match="failed to resolve pinned ASR model.*offline"):
        MlxWhisperTranscriber(
            config(),
            dependencies=MlxWhisperDependencies(
                unavailable,
                lambda _path, **_kwargs: {"text": ""},
            ),
        ).prepare()

    def failed_transcription(_path: str, **_kwargs: object) -> object:
        raise RuntimeError("decoder failed")

    with pytest.raises(RuntimeError, match="decoder failed"):
        MlxWhisperTranscriber(
            config(),
            dependencies=MlxWhisperDependencies(
                lambda **_kwargs: "/cache/pinned-whisper",
                failed_transcription,
            ),
        ).transcribe(tmp_path / "audio.wav")


def test_construction_does_not_import_model_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_import() -> Any:
        raise AssertionError("model dependencies must remain lazy")

    monkeypatch.setattr(mlx_whisper_adapter, "_import_dependencies", unexpected_import)

    MlxWhisperTranscriber(config())
