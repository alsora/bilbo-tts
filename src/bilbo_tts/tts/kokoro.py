"""Lazy adapter for the pinned Kokoro-82M MLX model."""

from __future__ import annotations

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

ENGINE = "kokoro"
BACKEND = "mlx"
MODEL_ID = "mlx-community/Kokoro-82M-bf16"
MODEL_REVISION = "a71e4d38b236d968966a2002c4c895dbd12b1c3c"
SAMPLE_RATE_HZ = 24_000
VOICE_IDS = ("if_sara", "im_nicola")
WEIGHT_FILES = [
    "config.json",
    "kokoro-v1_0.safetensors",
    "voices/if_sara.safetensors",
    "voices/im_nicola.safetensors",
]
_GENERATION_LOCK = threading.Lock()
_ZERO_MARKER = "dzzèro"
_ZERO_SOURCE_PHONEMES = "dʦʦˈɛro"
_ZERO_TARGET_PHONEMES = "dzˈɛro"
_AZIENDA_MARKER = "ad-ziènda"
_AZIENDA_SOURCE_PHONEMES = "adʣjˈɛnda"
_AZIENDA_TARGET_PHONEMES = "adzjˈɛnda"
_AZIENDE_MARKER = "ad-ziènde"
_AZIENDE_SOURCE_PHONEMES = "adʣjˈɛnde"
_AZIENDE_TARGET_PHONEMES = "adzjˈɛnde"
_MEGLIO_MARKER = "mèllio"
_MEGLIO_SOURCE_PHONEMES = "mˈɛllio"
_MEGLIO_TARGET_PHONEMES = "mˈɛʎːo"
_IMPEGNANDOSI_MARKER = "impegnando-si"
_IMPEGNANDOSI_SOURCE_PHONEMES = "impeɲˈandosˈi"
_IMPEGNANDOSI_TARGET_PHONEMES = "impeɲˈandosi"
_CENTOVENTISETTE_MARKER = "centoventissètte"
_CENTOVENTISETTE_SOURCE_PHONEMES = "ʧentoventiSˈɛtːe"
_CENTOVENTISETTE_TARGET_PHONEMES = "ʧentoventisˈɛtːe"
_PHONEME_OVERRIDES = (
    (_ZERO_SOURCE_PHONEMES, _ZERO_TARGET_PHONEMES),
    (_AZIENDA_SOURCE_PHONEMES, _AZIENDA_TARGET_PHONEMES),
    (_AZIENDE_SOURCE_PHONEMES, _AZIENDE_TARGET_PHONEMES),
    (_MEGLIO_SOURCE_PHONEMES, _MEGLIO_TARGET_PHONEMES),
    (_IMPEGNANDOSI_SOURCE_PHONEMES, _IMPEGNANDOSI_TARGET_PHONEMES),
    (_CENTOVENTISETTE_SOURCE_PHONEMES, _CENTOVENTISETTE_TARGET_PHONEMES),
)
_PHONEME_OVERRIDE_MARKERS = (
    _ZERO_MARKER,
    _AZIENDA_MARKER,
    _AZIENDE_MARKER,
    _MEGLIO_MARKER,
    _IMPEGNANDOSI_MARKER,
    _CENTOVENTISETTE_MARKER,
)


class _Metal(Protocol):
    def is_available(self) -> bool: ...


class _MlxRandom(Protocol):
    def seed(self, seed: int) -> None: ...


class _MlxModule(Protocol):
    metal: _Metal
    random: _MlxRandom


class _NumpyModule(Protocol):
    float32: object


class _Array(Protocol):
    ndim: int
    shape: tuple[int, ...]
    dtype: object

    def tolist(self) -> object: ...


class _KokoroResult(Protocol):
    audio: _Array
    sample_rate: int


class _KokoroModel(Protocol):
    def generate(
        self,
        text: str,
        *,
        voice: str,
        speed: float,
        sample_rate: int,
        language: str,
    ) -> _KokoroResult: ...


class _Phonemizer(Protocol):
    def phonemize(self, text: str) -> tuple[str, list[int]]: ...

    def phonemize_long(self, text: str) -> list[tuple[str, list[int]]]: ...

    def _ids_from_phonemes(self, phonemes: str) -> list[int]: ...


class _PhonemizableKokoroModel(_KokoroModel, Protocol):
    def _get_phonemizer(self, language: str, voice: str) -> _Phonemizer: ...


class _KokoroModelClass(Protocol):
    def from_pretrained(self, path: str) -> _KokoroModel: ...


class _KokoroModule(Protocol):
    KokoroTTS: _KokoroModelClass


class _HubModule(Protocol):
    snapshot_download: Callable[..., str]


class _Dependencies(NamedTuple):
    kokoro: _KokoroModule
    hub: _HubModule
    mlx: _MlxModule
    numpy: _NumpyModule


class _ReviewedOverridePhonemizer:
    """Replace reviewed pronunciation markers after ordinary Italian G2P."""

    def __init__(self, base: _Phonemizer) -> None:
        self._base = base

    def phonemize(self, text: str) -> tuple[str, list[int]]:
        phonemes, _ids = self._base.phonemize(text)
        return self._replace(phonemes)

    def phonemize_long(self, text: str) -> list[tuple[str, list[int]]]:
        return [self._replace(phonemes) for phonemes, _ids in self._base.phonemize_long(text)]

    def _ids_from_phonemes(self, phonemes: str) -> list[int]:
        return self._base._ids_from_phonemes(phonemes)

    def _replace(self, phonemes: str) -> tuple[str, list[int]]:
        corrected = phonemes
        for source, target in _PHONEME_OVERRIDES:
            corrected = corrected.replace(source, target)
        return corrected, self._ids_from_phonemes(corrected)


class KokoroTtsEngine:
    """Generate native 24 kHz mono PCM with a pinned Italian Kokoro voice."""

    def __init__(self, candidate: TtsCandidateConfig) -> None:
        _validate_candidate(candidate)
        self._candidate = candidate
        self._model: _KokoroModel | None = None
        self._model_lock = threading.Lock()
        self._phoneme_override_installed = False
        self._capabilities = TtsCapabilities(
            engine=ENGINE,
            model=candidate.model,
            native_sample_rate_hz=SAMPLE_RATE_HZ,
            voice_modes=(VoiceMode.NAMED,),
            named_voice_ids=VOICE_IDS,
            supports_seed=True,
            supports_speed=True,
            supports_temperature=False,
            max_text_characters=None,
        )

    @property
    def capabilities(self) -> TtsCapabilities:
        """Return static behavior without importing model dependencies."""

        return self._capabilities

    def health(self) -> TtsHealth:
        """Check package and Metal availability without resolving model weights."""

        try:
            dependencies = _import_dependencies()
            if not dependencies.mlx.metal.is_available():
                return self._health(False, "MLX Metal acceleration is unavailable on this machine")
        except Exception as error:
            return self._health(
                False,
                f"Kokoro dependencies are unavailable; run in the kokoro Pixi environment: {error}",
            )
        return self._health(True, "Kokoro MLX dependencies and Metal are available")

    def synthesize(self, request: TtsRequest) -> TtsResult:
        """Generate one request while serializing MLX's global random seed."""

        validate_request(self.capabilities, request)
        if not 0 <= request.settings.seed <= 0xFFFFFFFF:
            raise TtsError("kokoro seed must be between 0 and 4294967295")
        if not 0.5 <= request.settings.speed <= 2.0:
            raise TtsError("kokoro speed must be between 0.5 and 2.0")
        dependencies = _import_dependencies()
        if not dependencies.mlx.metal.is_available():
            raise TtsError("kokoro requires MLX Metal on Apple Silicon")
        model = self._load_model(dependencies)
        if any(marker in request.spoken_text for marker in _PHONEME_OVERRIDE_MARKERS):
            self._install_phoneme_overrides(model)
        try:
            with _GENERATION_LOCK:
                dependencies.mlx.random.seed(request.settings.seed)
                generated = model.generate(
                    request.spoken_text,
                    voice=request.voice.voice_id,
                    speed=request.settings.speed,
                    sample_rate=SAMPLE_RATE_HZ,
                    language="it",
                )
        except Exception as error:
            if _is_memory_error(error):
                raise TtsError(
                    "kokoro exhausted Metal memory; close other GPU workloads and retry "
                    "this excerpt"
                ) from error
            raise TtsError(f"kokoro MLX/Metal generation failed: {error}") from error

        pcm = _kokoro_pcm(generated, dependencies.numpy)
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

    def _install_phoneme_overrides(self, model: _KokoroModel) -> None:
        if self._phoneme_override_installed:
            return
        phonemizable = cast(_PhonemizableKokoroModel, model)
        try:
            original = phonemizable._get_phonemizer

            def overridden(language: str, voice: str) -> _Phonemizer:
                return _ReviewedOverridePhonemizer(original(language, voice))

            phonemizable._get_phonemizer = overridden  # type: ignore[method-assign]
        except (AttributeError, TypeError) as error:
            raise TtsError(
                "pinned Kokoro runtime does not expose the required phonemizer boundary"
            ) from error
        self._phoneme_override_installed = True

    def _health(self, healthy: bool, detail: str) -> TtsHealth:
        return TtsHealth(
            engine=ENGINE,
            model=self.capabilities.model,
            healthy=healthy,
            detail=detail,
        )

    def _load_model(self, dependencies: _Dependencies) -> _KokoroModel:
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
                model = dependencies.kokoro.KokoroTTS.from_pretrained(snapshot_path)
            except Exception as error:
                if _is_memory_error(error):
                    raise TtsError(
                        "kokoro could not load because Metal memory was exhausted; close "
                        "other GPU workloads and retry"
                    ) from error
                raise TtsError(
                    f"failed to resolve or load pinned Kokoro model {MODEL_ID}@"
                    f"{MODEL_REVISION}: {error}"
                ) from error
            self._model = model
            return model


def create_engine(candidate: TtsCandidateConfig, _project_root: Path) -> KokoroTtsEngine:
    """Construct the lazy Kokoro adapter."""

    return KokoroTtsEngine(candidate)


def _import_dependencies() -> _Dependencies:
    try:
        kokoro = cast(_KokoroModule, import_module("kokoro_mlx"))
        hub = cast(_HubModule, import_module("huggingface_hub"))
        mlx = cast(_MlxModule, import_module("mlx.core"))
        numpy = cast(_NumpyModule, import_module("numpy"))
    except Exception as error:
        raise TtsError(
            "Kokoro dependencies could not be imported; run this command with "
            f"`pixi run -e kokoro`: {error}"
        ) from error
    return _Dependencies(kokoro, hub, mlx, numpy)


def _validate_candidate(candidate: TtsCandidateConfig) -> None:
    if candidate.engine != ENGINE:
        raise TtsError(f"kokoro adapter received engine {candidate.engine!r}")
    if candidate.backend != BACKEND:
        raise TtsError(f"kokoro requires backend {BACKEND!r}, got {candidate.backend!r}")
    if candidate.model_id != MODEL_ID or candidate.model.revision != MODEL_REVISION:
        raise TtsError(f"kokoro requires pinned model {MODEL_ID}@{MODEL_REVISION}")
    if candidate.code_revision is not None:
        raise TtsError("kokoro does not accept a code_revision")
    if candidate.settings.sample_rate_hz != SAMPLE_RATE_HZ:
        raise TtsError(f"kokoro requires {SAMPLE_RATE_HZ} Hz output")
    if candidate.settings.temperature is not None:
        raise TtsError("kokoro does not support temperature")
    if not 0 <= candidate.settings.seed <= 0xFFFFFFFF:
        raise TtsError("kokoro seed must be between 0 and 4294967295")
    if not 0.5 <= candidate.settings.speed <= 2.0:
        raise TtsError("kokoro speed must be between 0.5 and 2.0")
    if candidate.voice.reference_path is not None:
        raise TtsError("kokoro does not support reference audio")
    if candidate.voice.voice_id not in VOICE_IDS:
        supported = ", ".join(VOICE_IDS)
        raise TtsError(
            f"kokoro does not support named voice {candidate.voice.voice_id!r}; "
            f"supported Italian voices: {supported}"
        )
    if candidate.inference_parameters:
        names = ", ".join(sorted(candidate.inference_parameters))
        raise TtsError(f"kokoro does not support inference parameters; got: {names}")


def _kokoro_pcm(generated: _KokoroResult, numpy: _NumpyModule) -> bytes:
    try:
        sample_rate = generated.sample_rate
        audio = generated.audio
    except Exception as error:
        raise TtsError("kokoro returned audio without valid result metadata") from error
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, int)
        or sample_rate != SAMPLE_RATE_HZ
    ):
        raise TtsError(
            f"kokoro returned invalid sample rate {sample_rate}; expected {SAMPLE_RATE_HZ}"
        )
    try:
        shape = tuple(audio.shape)
        dimensions = audio.ndim
    except (AttributeError, TypeError) as error:
        raise TtsError("kokoro returned audio without valid shape metadata") from error
    if (
        isinstance(dimensions, bool)
        or not isinstance(dimensions, int)
        or dimensions != 1
        or len(shape) != 1
        or isinstance(shape[0], bool)
        or not isinstance(shape[0], int)
        or shape[0] <= 0
    ):
        raise TtsError(
            f"kokoro returned invalid audio shape {shape}; expected one-dimensional audio"
        )
    try:
        dtype = audio.dtype
    except Exception as error:
        raise TtsError("kokoro returned audio without dtype metadata") from error
    if dtype != numpy.float32:
        raise TtsError("kokoro returned audio with invalid dtype; expected NumPy float32")
    try:
        samples = cast(list[object], audio.tolist())
    except Exception as error:
        raise TtsError("kokoro returned audio that cannot be converted to PCM") from error
    return float_samples_to_pcm_s16le(samples)


def _is_memory_error(error: Exception) -> bool:
    message = f"{type(error).__name__}: {error}".lower()
    return "outofmemory" in message or "out of memory" in message or "memory exhausted" in message
