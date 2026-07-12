"""Lazy adapter for the pinned Italian MLX-Whisper model."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import import_module
from pathlib import Path
from typing import NamedTuple, Protocol, cast

from bilbo_tts.asr.contracts import AsrError

ENGINE = "mlx-whisper"
BACKEND = "mlx"
MODEL_ID = "mlx-community/whisper-large-v3-turbo"
MODEL_REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"
LANGUAGE = "it"


class MlxWhisperConfig(Protocol):
    """Configuration fields required by the MLX-Whisper adapter."""

    @property
    def engine(self) -> str: ...

    @property
    def backend(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def revision(self) -> str: ...

    @property
    def language(self) -> str: ...


class MlxWhisperDependencies(NamedTuple):
    """Injectable MLX-Whisper boundary for dependency-free tests."""

    snapshot_download: Callable[..., str]
    transcribe: Callable[..., object]


class MlxWhisperTranscriber:
    """Transcribe WAV files with one lazily resolved pinned model snapshot."""

    def __init__(
        self,
        config: MlxWhisperConfig,
        *,
        dependencies: MlxWhisperDependencies | None = None,
    ) -> None:
        _validate_config(config)
        self._config = config
        self._dependencies = dependencies
        self._snapshot: str | None = None

    def prepare(self) -> None:
        """Resolve the pinned snapshot once without transcribing audio."""

        self._resolve_snapshot()

    def transcribe(self, wav_path: Path) -> str:
        """Transcribe one WAV with deterministic Italian inference settings."""

        dependencies = self._loaded_dependencies()
        snapshot = self._resolve_snapshot()
        response = dependencies.transcribe(
            str(wav_path.expanduser().resolve()),
            path_or_hf_repo=snapshot,
            language=LANGUAGE,
            task="transcribe",
            temperature=0.0,
            fp16=True,
            verbose=None,
            word_timestamps=False,
        )
        return _transcript_text(response)

    def _loaded_dependencies(self) -> MlxWhisperDependencies:
        if self._dependencies is None:
            self._dependencies = _import_dependencies()
        return self._dependencies

    def _resolve_snapshot(self) -> str:
        if self._snapshot is not None:
            return self._snapshot
        try:
            snapshot = self._loaded_dependencies().snapshot_download(
                repo_id=self._config.model_id,
                revision=self._config.revision,
            )
        except Exception as error:
            raise AsrError(
                f"failed to resolve pinned ASR model {self._config.model_id}@"
                f"{self._config.revision}: {error}"
            ) from error
        if not isinstance(snapshot, str) or not snapshot:
            raise AsrError("pinned ASR model resolution returned an invalid local path")
        self._snapshot = snapshot
        return snapshot


def _import_dependencies() -> MlxWhisperDependencies:
    try:
        hub = import_module("huggingface_hub")
        whisper = import_module("mlx_whisper")
        snapshot_download = cast(Callable[..., str], hub.snapshot_download)
        transcribe = cast(Callable[..., object], whisper.transcribe)
    except Exception as error:
        raise AsrError(
            "MLX-Whisper dependencies could not be imported; run this command with "
            f"`pixi run -e asr`: {error}"
        ) from error
    return MlxWhisperDependencies(snapshot_download=snapshot_download, transcribe=transcribe)


def _validate_config(config: MlxWhisperConfig) -> None:
    if config.model_id != MODEL_ID or config.revision != MODEL_REVISION:
        raise AsrError(
            f"ASR qualification requires pinned model {MODEL_ID}@{MODEL_REVISION}; "
            f"got {config.model_id}@{config.revision}"
        )
    if config.engine != ENGINE or config.backend != BACKEND or config.language != LANGUAGE:
        raise AsrError("ASR qualification requires the committed Italian MLX config")


def _transcript_text(response: object) -> str:
    if not isinstance(response, Mapping):
        raise AsrError("MLX-Whisper returned a non-mapping transcription result")
    text = response.get("text")
    if not isinstance(text, str):
        raise AsrError("MLX-Whisper transcription result is missing string field 'text'")
    return text
