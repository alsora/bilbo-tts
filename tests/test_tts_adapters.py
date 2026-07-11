from __future__ import annotations

import hashlib
import math
import random
import struct
from pathlib import Path
from typing import Any, cast

import pytest

from bilbo_tts.config import VoiceConfig
from bilbo_tts.models import SynthesisSettings
from bilbo_tts.qualification.candidates import (
    TtsCandidateConfig,
    candidate_path,
    load_tts_candidate,
)
from bilbo_tts.tts import TtsError, TtsRequest
from bilbo_tts.tts import chatterbox as chatterbox_adapter
from bilbo_tts.tts import kokoro as kokoro_adapter
from bilbo_tts.tts.audio import float_samples_to_pcm_s16le
from bilbo_tts.tts.factory import create_tts_engine

ROOT = Path(__file__).parents[1]


class FakeMps:
    def __init__(self, available: bool = True) -> None:
        self.available = available

    def is_available(self) -> bool:
        return self.available


class FakeBackends:
    def __init__(self, available: bool = True) -> None:
        self.mps = FakeMps(available)


class FakeTorch:
    def __init__(self, events: list[tuple[str, object]], available: bool = True) -> None:
        self.backends = FakeBackends(available)
        self.float32 = object()
        self.events = events

    def manual_seed(self, seed: int) -> object:
        self.events.append(("torch", seed))
        return object()


class FakeNumpyRandom:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events

    def seed(self, seed: int) -> None:
        self.events.append(("numpy", seed))


class FakeNumpy:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.random = FakeNumpyRandom(events)
        self.float32 = object()


class FakeTensor:
    def __init__(
        self,
        samples: list[float],
        dtype: object,
        *,
        shape: tuple[int, ...] | None = None,
    ) -> None:
        self.samples = samples
        self.dtype = dtype
        self.shape = shape or (1, len(samples))

    def __getitem__(self, index: int) -> FakeTensor:
        if index != 0:
            raise IndexError(index)
        return FakeTensor(self.samples, self.dtype, shape=(len(self.samples),))

    def detach(self) -> FakeTensor:
        return self

    def cpu(self) -> FakeTensor:
        return self

    def tolist(self) -> object:
        return list(self.samples)


class FakeChatterboxModel:
    def __init__(
        self,
        tensor: FakeTensor,
        events: list[tuple[str, object]],
        error: Exception | None = None,
    ) -> None:
        self.tensor = tensor
        self.events = events
        self.error = error
        self.calls: list[dict[str, object]] = []

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
    ) -> FakeTensor:
        self.events.append(("generate", text))
        self.calls.append(
            {
                "text": text,
                "language_id": language_id,
                "audio_prompt_path": audio_prompt_path,
                "exaggeration": exaggeration,
                "cfg_weight": cfg_weight,
                "temperature": temperature,
                "repetition_penalty": repetition_penalty,
                "min_p": min_p,
                "top_p": top_p,
            }
        )
        if self.error is not None:
            raise self.error
        return self.tensor


class FakeChatterboxLoader:
    def __init__(self, model: FakeChatterboxModel, error: Exception | None = None) -> None:
        self.model = model
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def from_local(
        self,
        path: str,
        *,
        device: str,
        t3_model: str,
    ) -> FakeChatterboxModel:
        self.calls.append((path, device, t3_model))
        if self.error is not None:
            raise self.error
        return self.model


class FakeChatterboxModule:
    def __init__(self, loader: FakeChatterboxLoader) -> None:
        self.ChatterboxMultilingualTTS = loader


class FakeHub:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def snapshot_download(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return "/cache/pinned-model"


class FakeMetal:
    def __init__(self, available: bool = True) -> None:
        self.available = available

    def is_available(self) -> bool:
        return self.available


class FakeMlxRandom:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events

    def seed(self, seed: int) -> None:
        self.events.append(("mlx", seed))


class FakeMlx:
    def __init__(self, events: list[tuple[str, object]], available: bool = True) -> None:
        self.metal = FakeMetal(available)
        self.random = FakeMlxRandom(events)


class FakeArray:
    def __init__(
        self,
        samples: list[float],
        dtype: object,
        *,
        shape: tuple[int, ...] | None = None,
        ndim: int = 1,
    ) -> None:
        self.samples = samples
        self.dtype = dtype
        self.shape = shape or (len(samples),)
        self.ndim = ndim

    def tolist(self) -> object:
        return list(self.samples)


class FakeKokoroResult:
    def __init__(self, audio: FakeArray, sample_rate: int = 24_000) -> None:
        self.audio = audio
        self.sample_rate = sample_rate


class FakeKokoroModel:
    def __init__(
        self,
        result: FakeKokoroResult,
        events: list[tuple[str, object]],
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.events = events
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        text: str,
        *,
        voice: str,
        speed: float,
        sample_rate: int,
        language: str,
    ) -> FakeKokoroResult:
        self.events.append(("generate", text))
        self.calls.append(
            {
                "text": text,
                "voice": voice,
                "speed": speed,
                "sample_rate": sample_rate,
                "language": language,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


class FakeKokoroLoader:
    def __init__(self, model: FakeKokoroModel, error: Exception | None = None) -> None:
        self.model = model
        self.error = error
        self.calls: list[str] = []

    def from_pretrained(self, path: str) -> FakeKokoroModel:
        self.calls.append(path)
        if self.error is not None:
            raise self.error
        return self.model


class FakeKokoroModule:
    def __init__(self, loader: FakeKokoroLoader) -> None:
        self.KokoroTTS = loader


def candidate(name: str) -> TtsCandidateConfig:
    return load_tts_candidate(candidate_path(ROOT, name))


def request(config: TtsCandidateConfig, *, text: str = "Breve testo italiano.") -> TtsRequest:
    return TtsRequest(spoken_text=text, voice=config.voice, settings=config.settings)


def chatterbox_dependencies(
    *,
    samples: list[float] | None = None,
    available: bool = True,
    generation_error: Exception | None = None,
    load_error: Exception | None = None,
    hub_error: Exception | None = None,
) -> tuple[
    chatterbox_adapter._Dependencies,
    FakeHub,
    FakeChatterboxLoader,
    FakeChatterboxModel,
    FakeTorch,
    list[tuple[str, object]],
]:
    events: list[tuple[str, object]] = []
    torch = FakeTorch(events, available)
    tensor = FakeTensor(samples or [-1.0, 0.0, 0.5, 1.0], torch.float32)
    model = FakeChatterboxModel(tensor, events, generation_error)
    loader = FakeChatterboxLoader(model, load_error)
    hub = FakeHub(hub_error)
    dependencies = chatterbox_adapter._Dependencies(
        cast(chatterbox_adapter._ChatterboxModule, FakeChatterboxModule(loader)),
        cast(chatterbox_adapter._HubModule, hub),
        cast(chatterbox_adapter._NumpyModule, FakeNumpy(events)),
        cast(chatterbox_adapter._TorchModule, torch),
    )
    return dependencies, hub, loader, model, torch, events


def kokoro_dependencies(
    *,
    samples: list[float] | None = None,
    available: bool = True,
    generation_error: Exception | None = None,
    load_error: Exception | None = None,
    hub_error: Exception | None = None,
) -> tuple[
    kokoro_adapter._Dependencies,
    FakeHub,
    FakeKokoroLoader,
    FakeKokoroModel,
    FakeNumpy,
    list[tuple[str, object]],
]:
    events: list[tuple[str, object]] = []
    numpy = FakeNumpy(events)
    array = FakeArray(samples or [-1.0, 0.0, 0.5, 1.0], numpy.float32)
    model = FakeKokoroModel(FakeKokoroResult(array), events, generation_error)
    loader = FakeKokoroLoader(model, load_error)
    hub = FakeHub(hub_error)
    dependencies = kokoro_adapter._Dependencies(
        cast(kokoro_adapter._KokoroModule, FakeKokoroModule(loader)),
        cast(kokoro_adapter._HubModule, hub),
        cast(kokoro_adapter._MlxModule, FakeMlx(events, available)),
        cast(kokoro_adapter._NumpyModule, numpy),
    )
    return dependencies, hub, loader, model, numpy, events


def test_pcm_conversion_is_dependency_free_strict_and_clipped() -> None:
    assert float_samples_to_pcm_s16le([-1.5, 0.0, 0.5, 1.5]) == struct.pack(
        "<hhhh", -32_768, 0, 16_384, 32_767
    )
    invalid_cases: list[tuple[list[object], str]] = [
        ([], "empty"),
        ([[0.0]], "one-dimensional"),
        ([True], "scalar"),
        ([math.nan], "finite"),
        ([math.inf], "finite"),
    ]
    for invalid, message in invalid_cases:
        with pytest.raises(TtsError, match=message):
            float_samples_to_pcm_s16le(invalid)


def test_factories_are_lazy_and_expose_exact_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_import() -> Any:
        raise AssertionError("dependencies must remain lazy")

    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", unexpected_import)
    monkeypatch.setattr(kokoro_adapter, "_import_dependencies", unexpected_import)

    chatterbox = create_tts_engine(candidate("chatterbox"), ROOT)
    kokoro = create_tts_engine(candidate("kokoro"), ROOT)

    assert chatterbox.capabilities.model.revision == chatterbox_adapter.MODEL_REVISION
    assert chatterbox.capabilities.max_text_characters == 300
    assert chatterbox.capabilities.supports_speed is False
    assert kokoro.capabilities.model.revision == kokoro_adapter.MODEL_REVISION
    assert kokoro.capabilities.named_voice_ids == ("if_sara", "im_nicola")
    assert kokoro.capabilities.max_text_characters is None


def test_chatterbox_success_uses_pins_settings_seed_order_and_pcm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies, hub, loader, model, _torch, events = chatterbox_dependencies()
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: dependencies)
    monkeypatch.setattr(
        random,
        "seed",
        lambda seed: events.append(("python", seed)),
    )
    config = candidate("chatterbox")
    engine = chatterbox_adapter.ChatterboxTtsEngine(config, ROOT)

    result = engine.synthesize(request(config))
    engine.synthesize(request(config, text="Secondo testo."))

    assert hub.calls == [
        {
            "repo_id": chatterbox_adapter.MODEL_ID,
            "revision": chatterbox_adapter.MODEL_REVISION,
            "allow_patterns": chatterbox_adapter.WEIGHT_FILES,
        }
    ]
    assert loader.calls == [("/cache/pinned-model", "mps", "v3")]
    assert events[:4] == [
        ("python", config.settings.seed),
        ("numpy", config.settings.seed),
        ("torch", config.settings.seed),
        ("generate", "Breve testo italiano."),
    ]
    assert model.calls[0] == {
        "text": "Breve testo italiano.",
        "language_id": "it",
        "audio_prompt_path": None,
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "temperature": 0.8,
        "repetition_penalty": 1.2,
        "min_p": 0.05,
        "top_p": 1.0,
    }
    assert result.pcm_s16le == struct.pack("<hhhh", -32_768, 0, 16_384, 32_767)
    assert result.model == config.model
    assert result.voice.voice_id == "builtin"
    assert result.settings == config.settings


def test_chatterbox_reference_is_root_bounded_and_checksum_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = tmp_path / "voices" / "owned.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"owned reference")
    checksum = hashlib.sha256(audio.read_bytes()).hexdigest()
    config = candidate("chatterbox").model_copy(
        update={
            "voice": VoiceConfig(
                voice_id="owned",
                reference_path="voices/owned.wav",
                reference_sha256=checksum,
            )
        }
    )
    dependencies, _hub, _loader, model, _torch, _events = chatterbox_dependencies()
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: dependencies)
    engine = chatterbox_adapter.ChatterboxTtsEngine(config, tmp_path)

    result = engine.synthesize(request(config))

    assert model.calls[0]["audio_prompt_path"] == str(audio.resolve())
    assert result.voice.reference_sha256 == checksum

    wrong = request(config).model_copy(
        update={
            "voice": VoiceConfig(
                voice_id="owned",
                reference_path="voices/owned.wav",
                reference_sha256="a" * 64,
            )
        }
    )
    with pytest.raises(TtsError, match="checksum mismatch"):
        engine.synthesize(wrong)

    outside = tmp_path.parent / "outside.wav"
    outside.write_bytes(b"outside")
    link = tmp_path / "voices" / "escape.wav"
    link.symlink_to(outside)
    unsafe = request(config).model_copy(
        update={
            "voice": VoiceConfig(
                voice_id="owned",
                reference_path="voices/escape.wav",
                reference_sha256=hashlib.sha256(b"outside").hexdigest(),
            )
        }
    )
    with pytest.raises(TtsError, match="below the project root"):
        engine.synthesize(unsafe)


@pytest.mark.parametrize(
    "change,message",
    [
        ({"backend": "mlx"}, "backend"),
        ({"model_id": "other/model"}, "pinned model"),
        ({"code_revision": "main"}, "code revision"),
        (
            {
                "settings": SynthesisSettings(
                    sample_rate_hz=24_000, seed=1, speed=1.1, temperature=0.8
                )
            },
            "speed",
        ),
        ({"inference_parameters": {}}, "configured keys"),
        (
            {
                "inference_parameters": {
                    "t3_model": "v2",
                    "exaggeration": 0.5,
                    "cfg_weight": 0.5,
                    "repetition_penalty": 1.2,
                    "min_p": 0.05,
                    "top_p": 1.0,
                }
            },
            "t3_model",
        ),
        (
            {
                "inference_parameters": {
                    "t3_model": "v3",
                    "exaggeration": True,
                    "cfg_weight": 0.5,
                    "repetition_penalty": 1.2,
                    "min_p": 0.05,
                    "top_p": 1.0,
                }
            },
            "must be a number",
        ),
    ],
)
def test_chatterbox_rejects_non_exact_candidate_configuration(
    change: dict[str, object],
    message: str,
) -> None:
    config = candidate("chatterbox").model_copy(update=change)
    with pytest.raises(TtsError, match=message):
        chatterbox_adapter.ChatterboxTtsEngine(config, ROOT)


def test_chatterbox_rejects_request_capabilities_and_invalid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = candidate("chatterbox")
    dependencies, _hub, _loader, model, torch, _events = chatterbox_dependencies()
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: dependencies)
    engine = chatterbox_adapter.ChatterboxTtsEngine(config, ROOT)

    too_long = request(config, text="x" * 301)
    with pytest.raises(TtsError, match="at most 300"):
        engine.synthesize(too_long)
    no_temperature = request(config).model_copy(
        update={"settings": config.settings.model_copy(update={"temperature": None})}
    )
    with pytest.raises(TtsError, match="requires temperature"):
        engine.synthesize(no_temperature)

    model.tensor = FakeTensor([0.0], torch.float32, shape=(2, 1))
    with pytest.raises(TtsError, match="invalid audio shape"):
        engine.synthesize(request(config))
    model.tensor = FakeTensor([0.0], object())
    with pytest.raises(TtsError, match="invalid dtype"):
        engine.synthesize(request(config))
    model.tensor = FakeTensor([2.0], torch.float32)
    assert engine.synthesize(request(config)).pcm_s16le == struct.pack("<h", 32_767)


def test_chatterbox_health_and_actionable_dependency_load_and_memory_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = candidate("chatterbox")
    dependencies, hub, _loader, _model, _torch, _events = chatterbox_dependencies()
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: dependencies)
    engine = chatterbox_adapter.ChatterboxTtsEngine(config, ROOT)
    assert engine.health().healthy is True
    assert hub.calls == []

    unavailable, *_rest = chatterbox_dependencies(available=False)
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: unavailable)
    assert engine.health().healthy is False
    with pytest.raises(TtsError, match="requires PyTorch MPS"):
        engine.synthesize(request(config))

    def missing() -> chatterbox_adapter._Dependencies:
        raise TtsError("missing package")

    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", missing)
    health = engine.health()
    assert health.healthy is False
    assert "chatterbox Pixi environment" in health.detail

    failing_load, *_rest = chatterbox_dependencies(hub_error=RuntimeError("offline"))
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: failing_load)
    with pytest.raises(TtsError, match="pinned Chatterbox model"):
        chatterbox_adapter.ChatterboxTtsEngine(config, ROOT).synthesize(request(config))

    oom, *_rest = chatterbox_dependencies(generation_error=RuntimeError("MPS out of memory"))
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: oom)
    with pytest.raises(TtsError, match="exhausted MPS memory"):
        chatterbox_adapter.ChatterboxTtsEngine(config, ROOT).synthesize(request(config))


def test_chatterbox_missing_dependency_error_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_name: str) -> Any:
        raise ModuleNotFoundError("not installed")

    monkeypatch.setattr(chatterbox_adapter, "import_module", missing)
    with pytest.raises(TtsError, match="pixi run -e chatterbox"):
        chatterbox_adapter._import_dependencies()


def test_kokoro_success_uses_pinned_snapshot_seed_settings_and_pcm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies, hub, loader, model, _numpy, events = kokoro_dependencies()
    monkeypatch.setattr(kokoro_adapter, "_import_dependencies", lambda: dependencies)
    config = candidate("kokoro")
    engine = kokoro_adapter.KokoroTtsEngine(config)

    result = engine.synthesize(request(config))
    engine.synthesize(request(config, text="Secondo testo."))

    assert hub.calls == [
        {
            "repo_id": kokoro_adapter.MODEL_ID,
            "revision": kokoro_adapter.MODEL_REVISION,
            "allow_patterns": kokoro_adapter.WEIGHT_FILES,
        }
    ]
    assert loader.calls == ["/cache/pinned-model"]
    assert events[:2] == [("mlx", config.settings.seed), ("generate", "Breve testo italiano.")]
    assert model.calls[0] == {
        "text": "Breve testo italiano.",
        "voice": "if_sara",
        "speed": 1.0,
        "sample_rate": 24_000,
        "language": "it",
    }
    assert result.pcm_s16le == struct.pack("<hhhh", -32_768, 0, 16_384, 32_767)
    assert result.model == config.model
    assert result.voice.voice_id == "if_sara"
    assert result.settings == config.settings


@pytest.mark.parametrize(
    "change,message",
    [
        ({"backend": "pytorch-mps"}, "backend"),
        ({"model_id": "other/model"}, "pinned model"),
        ({"code_revision": "main"}, "code_revision"),
        (
            {"settings": SynthesisSettings(sample_rate_hz=24_000, seed=1, temperature=0.8)},
            "temperature",
        ),
        (
            {"settings": SynthesisSettings(sample_rate_hz=24_000, seed=1, speed=2.1)},
            "speed",
        ),
        ({"voice": VoiceConfig(voice_id="unknown")}, "supported Italian voices"),
        ({"inference_parameters": {"temperature": 0.8}}, "does not support"),
    ],
)
def test_kokoro_rejects_non_exact_candidate_configuration(
    change: dict[str, object],
    message: str,
) -> None:
    config = candidate("kokoro").model_copy(update=change)
    with pytest.raises(TtsError, match=message):
        kokoro_adapter.KokoroTtsEngine(config)


def test_kokoro_rejects_request_capabilities_and_invalid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = candidate("kokoro")
    dependencies, _hub, _loader, model, numpy, _events = kokoro_dependencies()
    monkeypatch.setattr(kokoro_adapter, "_import_dependencies", lambda: dependencies)
    engine = kokoro_adapter.KokoroTtsEngine(config)

    too_fast = request(config).model_copy(
        update={"settings": config.settings.model_copy(update={"speed": 2.1})}
    )
    with pytest.raises(TtsError, match="between 0.5 and 2.0"):
        engine.synthesize(too_fast)
    with_reference = request(config).model_copy(
        update={
            "voice": VoiceConfig(
                voice_id="owned",
                reference_path="voice.wav",
                reference_sha256="a" * 64,
            )
        }
    )
    with pytest.raises(TtsError, match="does not support reference"):
        engine.synthesize(with_reference)

    model.result = FakeKokoroResult(FakeArray([0.0], numpy.float32), sample_rate=22_050)
    with pytest.raises(TtsError, match="invalid sample rate"):
        engine.synthesize(request(config))
    model.result = FakeKokoroResult(FakeArray([0.0], numpy.float32, shape=(1, 1), ndim=2))
    with pytest.raises(TtsError, match="invalid audio shape"):
        engine.synthesize(request(config))
    model.result = FakeKokoroResult(FakeArray([0.0], object()))
    with pytest.raises(TtsError, match="invalid dtype"):
        engine.synthesize(request(config))
    model.result = FakeKokoroResult(FakeArray([float("nan")], numpy.float32))
    with pytest.raises(TtsError, match="not finite"):
        engine.synthesize(request(config))


def test_kokoro_health_and_actionable_dependency_load_and_memory_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = candidate("kokoro")
    dependencies, hub, _loader, _model, _numpy, _events = kokoro_dependencies()
    monkeypatch.setattr(kokoro_adapter, "_import_dependencies", lambda: dependencies)
    engine = kokoro_adapter.KokoroTtsEngine(config)
    assert engine.health().healthy is True
    assert hub.calls == []

    unavailable, *_rest = kokoro_dependencies(available=False)
    monkeypatch.setattr(kokoro_adapter, "_import_dependencies", lambda: unavailable)
    assert engine.health().healthy is False
    with pytest.raises(TtsError, match="requires MLX Metal"):
        engine.synthesize(request(config))

    def missing() -> kokoro_adapter._Dependencies:
        raise TtsError("missing package")

    monkeypatch.setattr(kokoro_adapter, "_import_dependencies", missing)
    health = engine.health()
    assert health.healthy is False
    assert "kokoro Pixi environment" in health.detail

    failing_load, *_rest = kokoro_dependencies(load_error=RuntimeError("bad weights"))
    monkeypatch.setattr(kokoro_adapter, "_import_dependencies", lambda: failing_load)
    with pytest.raises(TtsError, match="pinned Kokoro model"):
        kokoro_adapter.KokoroTtsEngine(config).synthesize(request(config))

    oom, *_rest = kokoro_dependencies(generation_error=RuntimeError("Metal out of memory"))
    monkeypatch.setattr(kokoro_adapter, "_import_dependencies", lambda: oom)
    with pytest.raises(TtsError, match="exhausted Metal memory"):
        kokoro_adapter.KokoroTtsEngine(config).synthesize(request(config))


def test_kokoro_missing_dependency_error_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_name: str) -> Any:
        raise ModuleNotFoundError("not installed")

    monkeypatch.setattr(kokoro_adapter, "import_module", missing)
    with pytest.raises(TtsError, match="pixi run -e kokoro"):
        kokoro_adapter._import_dependencies()
