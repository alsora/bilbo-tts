from __future__ import annotations

import hashlib
import math
import random
import struct
from contextlib import AbstractContextManager, nullcontext
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


@pytest.fixture(autouse=True)
def supported_chatterbox_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chatterbox_adapter, "_macos_version", lambda: (26, 5, 2))


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
        self.float16 = object()
        self.bfloat16 = object()
        self.long = object()
        self.events = events

    def manual_seed(self, seed: int) -> object:
        self.events.append(("torch", seed))
        return object()

    def inference_mode(self) -> AbstractContextManager[None]:
        return nullcontext()

    def from_numpy(self, values: list[float]) -> FakeNumpyValues:
        return FakeNumpyValues(values, self.float32)


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


class FakeCastable:
    def __init__(self, events: list[tuple[str, object]], label: str) -> None:
        self.events = events
        self.label = label

    def to(self, *, dtype: object) -> FakeCastable:
        self.events.append((f"cast-{self.label}", dtype))
        return self


class FakeConditionals:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.t3 = FakeCastable(events, "conds")
        self.gen = {"ref": "builtin"}


class FakeWatermarker:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def apply_watermark(self, signal: object, *, sample_rate: int) -> object:
        self.calls.append(sample_rate)
        return signal


class FakeT3Config:
    start_text_token = 1
    stop_text_token = 2


class FakeTokenRow:
    def __init__(self, count: int) -> None:
        self.count = count

    @property
    def shape(self) -> tuple[int, ...]:
        return (self.count,)

    def to(self, _device: str) -> FakeTokenRow:
        return self


class FakeBatchedTokens:
    def __init__(self, row: FakeTokenRow) -> None:
        self.row = row

    def __getitem__(self, index: int) -> FakeTokenRow:
        assert index == 0
        return self.row


class FakeT3:
    def __init__(self, events: list[tuple[str, object]], row: FakeTokenRow) -> None:
        self.events = events
        self.row = row
        self.hp = FakeT3Config()
        self.turbo_calls: list[dict[str, object]] = []

    def to(self, *, dtype: object) -> FakeT3:
        self.events.append(("cast-t3", dtype))
        return self

    def inference_turbo(self, **kwargs: object) -> FakeBatchedTokens:
        self.turbo_calls.append(kwargs)
        return FakeBatchedTokens(self.row)


class FakeTextTokens:
    def __init__(self) -> None:
        self.targets: list[object] = []

    def to(self, target: object) -> FakeTextTokens:
        self.targets.append(target)
        return self


class FakeTokenizer:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events

    def text_to_tokens(self, text: str, *, language_id: str) -> FakeTextTokens:
        self.events.append(("tokenize", (text, language_id)))
        return FakeTextTokens()


class FakeWav:
    def __init__(self, samples: list[float]) -> None:
        self.samples = samples

    def squeeze(self, _dim: int) -> FakeWav:
        return self

    def detach(self) -> FakeWav:
        return self

    def cpu(self) -> FakeWav:
        return self

    def numpy(self) -> list[float]:
        return list(self.samples)


class FakeS3Gen:
    def __init__(self, wav: FakeWav) -> None:
        self.wav = wav
        self.calls: list[tuple[object, object]] = []

    def inference(self, *, speech_tokens: object, ref_dict: object) -> tuple[FakeWav, None]:
        self.calls.append((speech_tokens, ref_dict))
        return self.wav, None


class FakeNumpyValues:
    def __init__(self, values: list[float], dtype: object) -> None:
        self.values = values
        self.dtype = dtype

    def unsqueeze(self, _dim: int) -> FakeTensor:
        return FakeTensor(list(self.values), self.dtype)


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
        self.t3: object = FakeCastable(events, "t3")
        self.conds = FakeConditionals(events)
        self.watermarker: object = FakeWatermarker()
        self.tokenizer = FakeTokenizer(events)
        self.s3gen = FakeS3Gen(FakeWav([0.0]))

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


FAKE_MARKER_PHONEMES = {
    "dzzèro": "dʦʦˈɛro",
    "ad-ziènda": "adʣjˈɛnda",
    "ad-ziènde": "adʣjˈɛnde",
    "mèllio": "mˈɛllio",
    "impegnando-si": "impeɲˈandosˈi",
    "centoventissètte": "ʧentoventiSˈɛtːe",
}


class FakePhonemizer:
    """Mimic espeak-ng where each marker phonemizes identically in isolation and context."""

    def phonemize(self, text: str) -> tuple[str, list[int]]:
        phonemes = text
        for marker, source in FAKE_MARKER_PHONEMES.items():
            phonemes = phonemes.replace(marker, source)
        return phonemes, self._ids_from_phonemes(phonemes)

    def phonemize_long(self, text: str) -> list[tuple[str, list[int]]]:
        return [self.phonemize(text)]

    def _ids_from_phonemes(self, phonemes: str) -> list[int]:
        return [ord(character) for character in phonemes]


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
        self.phonemizer = FakePhonemizer()

    def _get_phonemizer(self, _language: str, _voice: str) -> FakePhonemizer:
        return self.phonemizer

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
    # Exact clipping and truncation-toward-zero boundaries must stay
    # byte-identical to the historical conversion or previously checksummed
    # WAV outputs would be invalidated.
    assert float_samples_to_pcm_s16le(
        [-1.0, 1.0, -0.999999, 0.999999, -0.5000001, 0.5000001]
    ) == struct.pack("<hhhhhh", -32_768, 32_767, -32_767, 32_767, -16_384, 16_384)
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


def chatterbox_variant(**overrides: object) -> TtsCandidateConfig:
    config = candidate("chatterbox")
    parameters = dict(config.inference_parameters)
    parameters.update(cast(dict[str, Any], overrides))
    return config.model_copy(update={"inference_parameters": parameters})


def test_chatterbox_fp16_casts_t3_and_builtin_conditionals_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies, _hub, _loader, model, torch, events = chatterbox_dependencies()
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: dependencies)
    config = chatterbox_variant(dtype="float16")
    engine = chatterbox_adapter.ChatterboxTtsEngine(config, ROOT)

    result = engine.synthesize(request(config))
    engine.synthesize(request(config, text="Secondo testo."))

    casts = [event for event in events if event[0].startswith("cast-")]
    assert casts == [("cast-t3", torch.float16), ("cast-conds", torch.float16)]
    assert not isinstance(model.watermarker, chatterbox_adapter._IdentityWatermarker)
    assert result.pcm_s16le == struct.pack("<hhhh", -32_768, 0, 16_384, 32_767)


def test_chatterbox_default_configuration_never_casts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies, _hub, _loader, model, _torch, events = chatterbox_dependencies()
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: dependencies)
    config = candidate("chatterbox")
    engine = chatterbox_adapter.ChatterboxTtsEngine(config, ROOT)

    engine.synthesize(request(config))

    assert not any(event[0].startswith("cast-") for event in events)
    assert not isinstance(model.watermarker, chatterbox_adapter._IdentityWatermarker)


def test_chatterbox_dtype_experiments_reject_reference_audio(tmp_path: Path) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"reference")
    config = chatterbox_variant(dtype="float16").model_copy(
        update={
            "voice": VoiceConfig(
                voice_id="owned",
                reference_path="voice.wav",
                reference_sha256=hashlib.sha256(b"reference").hexdigest(),
            )
        }
    )
    with pytest.raises(TtsError, match="float32 cfg"):
        chatterbox_adapter.ChatterboxTtsEngine(config, tmp_path)


def test_chatterbox_watermark_skip_replaces_watermarker_with_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies, _hub, _loader, model, _torch, _events = chatterbox_dependencies()
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: dependencies)
    config = chatterbox_variant(watermark=False)
    engine = chatterbox_adapter.ChatterboxTtsEngine(config, ROOT)

    result = engine.synthesize(request(config))

    assert isinstance(model.watermarker, chatterbox_adapter._IdentityWatermarker)
    assert result.pcm_s16le == struct.pack("<hhhh", -32_768, 0, 16_384, 32_767)
    signal = object()
    assert model.watermarker.apply_watermark(signal, sample_rate=24_000) is signal


def test_chatterbox_turbo_sampler_bypasses_cfg_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies, _hub, _loader, model, _torch, events = chatterbox_dependencies()
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: dependencies)
    pads: list[tuple[object, object]] = []

    def fake_pad(tokens: object, pad: object, value: object) -> object:
        pads.append((pad, value))
        return tokens

    helpers = chatterbox_adapter._TurboHelpers(
        punc_norm=lambda text: f"norm:{text}",
        drop_invalid_tokens=lambda tokens: tokens,
        pad=fake_pad,
        token_rate=25,
    )
    monkeypatch.setattr(chatterbox_adapter, "_import_turbo_helpers", lambda: helpers)

    row = FakeTokenRow(3)
    turbo_t3 = FakeT3(events, row)
    model.t3 = turbo_t3
    s3gen = FakeS3Gen(FakeWav([0.5] * 3_000))
    model.s3gen = s3gen
    watermarker = FakeWatermarker()
    model.watermarker = watermarker

    config = chatterbox_variant(sampler="turbo")
    engine = chatterbox_adapter.ChatterboxTtsEngine(config, ROOT)
    result = engine.synthesize(request(config))

    assert model.calls == []
    assert ("tokenize", ("norm:Breve testo italiano.", "it")) in events
    assert pads == [((1, 0), 1), ((0, 1), 2)]
    [turbo_call] = turbo_t3.turbo_calls
    assert isinstance(turbo_call.pop("text_tokens"), FakeTextTokens)
    assert turbo_call == {
        "t3_cond": model.conds.t3,
        "temperature": 0.8,
        "top_k": 1000,
        "top_p": 1.0,
        "repetition_penalty": 1.2,
        "max_gen_len": 1000,
    }
    assert s3gen.calls == [(row, model.conds.gen)]
    # Three tokens minus the trimmed final token at 960 samples per token.
    assert result.frame_count == 1_920
    assert watermarker.calls == [24_000]
    assert set(result.pcm_s16le) == set(struct.pack("<h", 16_384))


def test_chatterbox_fp16_engine_rejects_reference_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"reference")
    dependencies, *_rest = chatterbox_dependencies()
    monkeypatch.setattr(chatterbox_adapter, "_import_dependencies", lambda: dependencies)
    config = chatterbox_variant(dtype="float16")
    engine = chatterbox_adapter.ChatterboxTtsEngine(config, tmp_path)

    reference_request = request(config).model_copy(
        update={
            "voice": VoiceConfig(
                voice_id="owned",
                reference_path="voice.wav",
                reference_sha256=hashlib.sha256(b"reference").hexdigest(),
            )
        }
    )
    with pytest.raises(TtsError, match="float32 cfg"):
        engine.synthesize(reference_request)


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
        (
            {
                "inference_parameters": {
                    "t3_model": "v3",
                    "exaggeration": 0.5,
                    "cfg_weight": 0.5,
                    "repetition_penalty": 1.2,
                    "min_p": 0.05,
                    "top_p": 1.0,
                    "dtype": "int8",
                }
            },
            "'dtype' must be one of",
        ),
        (
            {
                "inference_parameters": {
                    "t3_model": "v3",
                    "exaggeration": 0.5,
                    "cfg_weight": 0.5,
                    "repetition_penalty": 1.2,
                    "min_p": 0.05,
                    "top_p": 1.0,
                    "watermark": "off",
                }
            },
            "'watermark' must be a boolean",
        ),
        (
            {
                "inference_parameters": {
                    "t3_model": "v3",
                    "exaggeration": 0.5,
                    "cfg_weight": 0.5,
                    "repetition_penalty": 1.2,
                    "min_p": 0.05,
                    "top_p": 1.0,
                    "sampler": "greedy",
                }
            },
            "'sampler' must be one of",
        ),
        (
            {
                "inference_parameters": {
                    "t3_model": "v3",
                    "exaggeration": 0.5,
                    "cfg_weight": 0.5,
                    "repetition_penalty": 1.2,
                    "min_p": 0.05,
                    "top_p": 1.0,
                    "batch_size": 2,
                }
            },
            "configured keys",
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

    monkeypatch.setattr(chatterbox_adapter, "_macos_version", lambda: (14, 8, 7))
    health = engine.health()
    assert health.healthy is False
    assert "macOS 15.1 or newer" in health.detail
    with pytest.raises(TtsError, match="macOS 15.1 or newer"):
        engine.synthesize(request(config))
    monkeypatch.setattr(chatterbox_adapter, "_macos_version", lambda: (26, 5, 2))

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


def test_kokoro_overlay_declares_expected_phoneme_overrides() -> None:
    assert kokoro_adapter._load_phoneme_overrides() == {
        "dzzèro": "dzˈɛro",
        "ad-ziènda": "adzjˈɛnda",
        "ad-ziènde": "adzjˈɛnde",
        "mèllio": "mˈɛʎːo",
        "impegnando-si": "impeɲˈandosi",
        "centoventissètte": "ʧentoventisˈɛtːe",
    }


def test_kokoro_markers_receive_reviewed_phoneme_sequences() -> None:
    phonemizer = kokoro_adapter._ReviewedOverridePhonemizer(
        FakePhonemizer(), kokoro_adapter._load_phoneme_overrides()
    )

    text = "prima dzzèro, ad-ziènda, ad-ziènde, mèllio, impegnando-si, e centoventissètte dopo"
    phonemes, token_ids = phonemizer.phonemize(text)
    long = phonemizer.phonemize_long(text)

    assert phonemes == (
        "prima dzˈɛro, adzjˈɛnda, adzjˈɛnde, mˈɛʎːo, impeɲˈandosi, e ʧentoventisˈɛtːe dopo"
    )
    assert token_ids == [ord(character) for character in phonemes]
    assert long == [(phonemes, token_ids)]


def test_kokoro_context_variant_marker_keeps_ordinary_phonemes() -> None:
    class ContextVariantPhonemizer(FakePhonemizer):
        """Render the pronoun marker with a reduced final vowel in running context."""

        def phonemize(self, text: str) -> tuple[str, list[int]]:
            if text == "impegnando-si a restituirlo":
                phonemes = "impeɲˈandosɪ a restitʊˈirlo"
                return phonemes, self._ids_from_phonemes(phonemes)
            return super().phonemize(text)

    phonemizer = kokoro_adapter._ReviewedOverridePhonemizer(
        ContextVariantPhonemizer(), kokoro_adapter._load_phoneme_overrides()
    )

    phonemes, _ids = phonemizer.phonemize("impegnando-si a restituirlo")

    assert phonemes == "impeɲˈandosɪ a restitʊˈirlo"


def test_kokoro_missing_overlay_error_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kokoro_adapter, "OVERRIDE_LEXICON_FILENAME", "missing-overlay.yaml")
    with pytest.raises(TtsError, match="reviewed Kokoro pronunciation overlay"):
        kokoro_adapter._load_phoneme_overrides()


@pytest.mark.parametrize(
    "marker,corrected_phonemes",
    [
        ("dzzèro", "dzˈɛro"),
        ("ad-ziènda", "adzjˈɛnda"),
        ("ad-ziènde", "adzjˈɛnde"),
        ("mèllio", "mˈɛʎːo"),
        ("impegnando-si", "impeɲˈandosi"),
        ("centoventissètte", "ʧentoventisˈɛtːe"),
    ],
)
def test_kokoro_engine_installs_phoneme_overrides_only_for_marker(
    monkeypatch: pytest.MonkeyPatch,
    marker: str,
    corrected_phonemes: str,
) -> None:
    dependencies, _hub, _loader, model, _numpy, _events = kokoro_dependencies()
    monkeypatch.setattr(kokoro_adapter, "_import_dependencies", lambda: dependencies)
    config = candidate("kokoro")
    engine = kokoro_adapter.KokoroTtsEngine(config)

    engine.synthesize(request(config))
    assert isinstance(model._get_phonemizer("it", "if_sara"), FakePhonemizer)

    engine.synthesize(request(config, text=marker))
    corrected = model._get_phonemizer("it", "if_sara")

    assert isinstance(corrected, kokoro_adapter._ReviewedOverridePhonemizer)
    assert corrected.phonemize(f"prima {marker} dopo")[0] == f"prima {corrected_phonemes} dopo"


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
