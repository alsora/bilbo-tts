"""Lazy adapter for official Chatterbox Multilingual V3 on PyTorch MPS."""

from __future__ import annotations

import hashlib
import hmac
import math
import platform
import random
import threading
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import NamedTuple, Protocol, cast

from bilbo_tts.qualification.candidates import TtsCandidateConfig
from bilbo_tts.tts.audio import float_samples_to_pcm_s16le
from bilbo_tts.tts.contracts import (
    TtsCapabilities,
    TtsError,
    TtsHealth,
    TtsRequest,
    TtsResult,
    VoiceMode,
)
from bilbo_tts.tts.validation import validate_request, validate_result, voice_identity

ENGINE = "chatterbox"
BACKEND = "pytorch-mps"
MODEL_ID = "ResembleAI/chatterbox"
MODEL_REVISION = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
CODE_REVISION = "65b18437192794391a0308a8f705b1e33e633948"
SAMPLE_RATE_HZ = 24_000
MAX_TEXT_CHARACTERS = 300
MINIMUM_MACOS = (15, 1)
WEIGHT_FILES = [
    "ve.pt",
    "t3_mtl23ls_v3.safetensors",
    "s3gen.pt",
    "grapheme_mtl_merged_expanded_v1.json",
    "conds.pt",
    "Cangjie5_TC.json",
]
_PARAMETER_NAMES = {
    "t3_model",
    "exaggeration",
    "cfg_weight",
    "repetition_penalty",
    "min_p",
    "top_p",
}
_GENERATION_LOCK = threading.Lock()


class _MpsBackend(Protocol):
    def is_available(self) -> bool: ...


class _TorchBackends(Protocol):
    mps: _MpsBackend


class _TorchModule(Protocol):
    backends: _TorchBackends
    float32: object

    def manual_seed(self, seed: int) -> object: ...


class _NumpyRandom(Protocol):
    def seed(self, seed: int) -> None: ...


class _NumpyModule(Protocol):
    random: _NumpyRandom


class _Tensor(Protocol):
    shape: tuple[int, ...]
    dtype: object

    def __getitem__(self, index: int) -> _Tensor: ...

    def detach(self) -> _Tensor: ...

    def cpu(self) -> _Tensor: ...

    def tolist(self) -> object: ...


class _ChatterboxModel(Protocol):
    def generate(
        self,
        text: str,
        *,
        language_id: str,
        audio_prompt_path: str | None,
        exaggeration: float,
        cfg_weight: float,
        temperature: float,
        repetition_penalty: float,
        min_p: float,
        top_p: float,
    ) -> _Tensor: ...


class _ChatterboxModelClass(Protocol):
    def from_local(
        self,
        path: str,
        *,
        device: str,
        t3_model: str,
    ) -> _ChatterboxModel: ...


class _ChatterboxModule(Protocol):
    ChatterboxMultilingualTTS: _ChatterboxModelClass


class _HubModule(Protocol):
    snapshot_download: Callable[..., str]


class _Dependencies(NamedTuple):
    chatterbox: _ChatterboxModule
    hub: _HubModule
    numpy: _NumpyModule
    torch: _TorchModule


class ChatterboxTtsEngine:
    """Generate exact 24 kHz mono PCM through pinned Chatterbox V3."""

    def __init__(self, candidate: TtsCandidateConfig, project_root: Path) -> None:
        parameters = _validated_parameters(candidate)
        self._candidate = candidate
        self._project_root = project_root.expanduser().resolve()
        self._exaggeration = parameters["exaggeration"]
        self._cfg_weight = parameters["cfg_weight"]
        self._repetition_penalty = parameters["repetition_penalty"]
        self._min_p = parameters["min_p"]
        self._top_p = parameters["top_p"]
        self._model: _ChatterboxModel | None = None
        self._model_lock = threading.Lock()
        self._capabilities = TtsCapabilities(
            engine=ENGINE,
            model=candidate.model,
            native_sample_rate_hz=SAMPLE_RATE_HZ,
            voice_modes=(VoiceMode.NAMED, VoiceMode.REFERENCE),
            named_voice_ids=("builtin",),
            supports_seed=True,
            supports_speed=False,
            supports_temperature=True,
            max_text_characters=MAX_TEXT_CHARACTERS,
        )

    @property
    def capabilities(self) -> TtsCapabilities:
        """Return static behavior without importing model dependencies."""

        return self._capabilities

    def health(self) -> TtsHealth:
        """Check imports and MPS availability without resolving model weights."""

        if _macos_version() < MINIMUM_MACOS:
            return self._health(False, _unsupported_macos_message())
        try:
            dependencies = _import_dependencies()
            if not dependencies.torch.backends.mps.is_available():
                return self._health(False, "PyTorch MPS is unavailable on this machine")
        except Exception as error:
            return self._health(
                False,
                f"Chatterbox dependencies are unavailable; run in the chatterbox Pixi "
                f"environment: {error}",
            )
        return self._health(True, "Chatterbox V3 dependencies and PyTorch MPS are available")

    def synthesize(self, request: TtsRequest) -> TtsResult:
        """Generate one request with global random states serialized."""

        validate_request(self.capabilities, request)
        if _macos_version() < MINIMUM_MACOS:
            raise TtsError(_unsupported_macos_message())
        if not 0 <= request.settings.seed <= 0xFFFFFFFF:
            raise TtsError("chatterbox seed must be between 0 and 4294967295")
        if request.settings.temperature is None:
            raise TtsError("chatterbox requires temperature to be set")
        if request.settings.temperature <= 0:
            raise TtsError("chatterbox temperature must be greater than zero")
        reference_path = self._resolve_reference(request)
        dependencies = _import_dependencies()
        if not dependencies.torch.backends.mps.is_available():
            raise TtsError(
                "chatterbox requires PyTorch MPS; use Apple Silicon with an MPS-enabled "
                "PyTorch build"
            )
        model = self._load_model(dependencies)
        try:
            with _GENERATION_LOCK:
                random.seed(request.settings.seed)
                dependencies.numpy.random.seed(request.settings.seed)
                dependencies.torch.manual_seed(request.settings.seed)
                audio = model.generate(
                    request.spoken_text,
                    language_id="it",
                    audio_prompt_path=reference_path,
                    exaggeration=self._exaggeration,
                    cfg_weight=self._cfg_weight,
                    temperature=request.settings.temperature,
                    repetition_penalty=self._repetition_penalty,
                    min_p=self._min_p,
                    top_p=self._top_p,
                )
        except Exception as error:
            if _is_memory_error(error):
                raise TtsError(
                    "chatterbox exhausted MPS memory; close other GPU workloads and retry "
                    "this excerpt"
                ) from error
            raise TtsError(f"chatterbox generation failed: {error}") from error

        pcm = _chatterbox_pcm(audio, dependencies.torch)
        frame_count = len(pcm) // 2
        result = TtsResult(
            pcm_s16le=pcm,
            sample_rate_hz=SAMPLE_RATE_HZ,
            frame_count=frame_count,
            duration_seconds=frame_count / SAMPLE_RATE_HZ,
            model=self.capabilities.model,
            voice=voice_identity(request),
            settings=request.settings,
        )
        validate_result(self.capabilities, request, result)
        return result

    def _health(self, healthy: bool, detail: str) -> TtsHealth:
        return TtsHealth(
            engine=ENGINE,
            model=self.capabilities.model,
            healthy=healthy,
            detail=detail,
        )

    def _load_model(self, dependencies: _Dependencies) -> _ChatterboxModel:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                snapshot_path = dependencies.hub.snapshot_download(
                    repo_id=MODEL_ID,
                    revision=MODEL_REVISION,
                    allow_patterns=WEIGHT_FILES,
                )
                model = dependencies.chatterbox.ChatterboxMultilingualTTS.from_local(
                    snapshot_path,
                    device="mps",
                    t3_model="v3",
                )
            except Exception as error:
                if _is_memory_error(error):
                    raise TtsError(
                        "chatterbox could not load on MPS because memory was exhausted; "
                        "close other GPU workloads and retry"
                    ) from error
                raise TtsError(
                    f"failed to resolve or load pinned Chatterbox model {MODEL_ID}@"
                    f"{MODEL_REVISION}: {error}"
                ) from error
            self._model = model
            return model

    def _resolve_reference(self, request: TtsRequest) -> str | None:
        relative_path = request.voice.reference_path
        expected_checksum = request.voice.reference_sha256
        if relative_path is None or expected_checksum is None:
            return None
        try:
            resolved = (self._project_root / relative_path).resolve(strict=True)
            resolved.relative_to(self._project_root)
        except (OSError, ValueError) as error:
            raise TtsError(
                "chatterbox reference audio must resolve to an existing file below the "
                f"project root: {relative_path}"
            ) from error
        if not resolved.is_file():
            raise TtsError(f"chatterbox reference audio is not a file: {relative_path}")
        try:
            actual_checksum = _file_sha256(resolved)
        except OSError as error:
            raise TtsError(
                f"cannot read chatterbox reference audio {relative_path}: {error}"
            ) from error
        if not hmac.compare_digest(actual_checksum, expected_checksum):
            raise TtsError(
                f"chatterbox reference checksum mismatch for {relative_path}: expected "
                f"{expected_checksum}, got {actual_checksum}"
            )
        return str(resolved)


def create_engine(candidate: TtsCandidateConfig, project_root: Path) -> ChatterboxTtsEngine:
    """Construct the lazy Chatterbox adapter."""

    return ChatterboxTtsEngine(candidate, project_root)


def _import_dependencies() -> _Dependencies:
    try:
        chatterbox = cast(_ChatterboxModule, import_module("chatterbox.mtl_tts"))
        hub = cast(_HubModule, import_module("huggingface_hub"))
        numpy = cast(_NumpyModule, import_module("numpy"))
        torch = cast(_TorchModule, import_module("torch"))
    except Exception as error:
        raise TtsError(
            "Chatterbox dependencies could not be imported; run this command with "
            f"`pixi run -e chatterbox`: {error}"
        ) from error
    return _Dependencies(chatterbox, hub, numpy, torch)


def _validated_parameters(candidate: TtsCandidateConfig) -> dict[str, float]:
    if candidate.engine != ENGINE:
        raise TtsError(f"chatterbox adapter received engine {candidate.engine!r}")
    if candidate.backend != BACKEND:
        raise TtsError(f"chatterbox requires backend {BACKEND!r}, got {candidate.backend!r}")
    if candidate.model_id != MODEL_ID or candidate.model.revision != MODEL_REVISION:
        raise TtsError(f"chatterbox requires pinned model {MODEL_ID}@{MODEL_REVISION}")
    if candidate.code_revision != CODE_REVISION:
        raise TtsError(f"chatterbox requires code revision {CODE_REVISION}")
    if candidate.settings.sample_rate_hz != SAMPLE_RATE_HZ:
        raise TtsError(f"chatterbox requires {SAMPLE_RATE_HZ} Hz output")
    if candidate.settings.speed != 1.0:
        raise TtsError("chatterbox speed must be exactly 1.0")
    if not 0 <= candidate.settings.seed <= 0xFFFFFFFF:
        raise TtsError("chatterbox seed must be between 0 and 4294967295")
    if candidate.settings.temperature is None or candidate.settings.temperature <= 0:
        raise TtsError("chatterbox requires a positive temperature")
    if candidate.voice.reference_path is None and candidate.voice.voice_id != "builtin":
        raise TtsError("chatterbox built-in voice must use voice_id 'builtin'")
    names = set(candidate.inference_parameters)
    if names != _PARAMETER_NAMES:
        missing = sorted(_PARAMETER_NAMES - names)
        unexpected = sorted(names - _PARAMETER_NAMES)
        raise TtsError(
            f"chatterbox inference parameters must use exactly the configured keys; "
            f"missing={missing}, unexpected={unexpected}"
        )
    if candidate.inference_parameters["t3_model"] != "v3":
        raise TtsError("chatterbox t3_model must be exactly 'v3'")
    return {
        "exaggeration": _number_in_range(candidate, "exaggeration", 0.0, 1.0),
        "cfg_weight": _number_in_range(candidate, "cfg_weight", 0.0, 1.0),
        "repetition_penalty": _number_in_range(candidate, "repetition_penalty", 0.01, 10.0),
        "min_p": _number_in_range(candidate, "min_p", 0.0, 1.0),
        "top_p": _number_in_range(candidate, "top_p", 0.0, 1.0),
    }


def _number_in_range(
    candidate: TtsCandidateConfig,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    value = candidate.inference_parameters[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TtsError(f"chatterbox inference parameter {name!r} must be a number")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise TtsError(
            f"chatterbox inference parameter {name!r} must be between {minimum} and {maximum}"
        )
    return number


def _chatterbox_pcm(audio: _Tensor, torch: _TorchModule) -> bytes:
    try:
        shape = tuple(audio.shape)
    except (AttributeError, TypeError) as error:
        raise TtsError("chatterbox returned audio without valid shape metadata") from error
    if (
        len(shape) != 2
        or any(isinstance(dimension, bool) or not isinstance(dimension, int) for dimension in shape)
        or shape[0] != 1
        or shape[1] <= 0
    ):
        raise TtsError(f"chatterbox returned invalid audio shape {shape}; expected (1, samples)")
    try:
        dtype = audio.dtype
    except Exception as error:
        raise TtsError("chatterbox returned audio without dtype metadata") from error
    if dtype != torch.float32:
        raise TtsError("chatterbox returned audio with invalid dtype; expected torch.float32")
    try:
        samples = cast(list[object], audio[0].detach().cpu().tolist())
    except Exception as error:
        raise TtsError("chatterbox returned audio that cannot be converted to PCM") from error
    return float_samples_to_pcm_s16le(samples)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_memory_error(error: Exception) -> bool:
    message = f"{type(error).__name__}: {error}".lower()
    return "outofmemory" in message or "out of memory" in message or "memory exhausted" in message


def _macos_version() -> tuple[int, ...]:
    version = platform.mac_ver()[0]
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return ()


def _unsupported_macos_message() -> str:
    detected = platform.mac_ver()[0] or "unknown"
    return (
        "chatterbox requires macOS 15.1 or newer for reliable PyTorch MPS generation; "
        f"found macOS {detected}"
    )
