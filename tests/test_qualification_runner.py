from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from bilbo_tts.config import VoiceConfig
from bilbo_tts.models import ModelIdentity, SynthesisSettings
from bilbo_tts.qualification.candidates import (
    CandidateEngine,
    LicenseMetadata,
    TtsCandidateConfig,
)
from bilbo_tts.qualification.corpus import (
    REQUIRED_CATEGORIES,
    CorpusCategory,
    CorpusExcerpt,
    QualificationCorpus,
)
from bilbo_tts.qualification.listening import prepare_listening_package
from bilbo_tts.qualification.results import QualificationError, load_qualification_result
from bilbo_tts.qualification.runner import (
    qualify_tts,
    render_qualification_report,
    run_qualification,
)
from bilbo_tts.tts import FakeTtsEngine, TtsCapabilities, TtsHealth, TtsRequest, TtsResult

ROOT = Path(__file__).parents[1]


def small_corpus() -> QualificationCorpus:
    excerpts = []
    for index in range(24):
        categories = tuple(REQUIRED_CATEGORIES) if index == 0 else (CorpusCategory.ORDINARY_PROSE,)
        excerpts.append(
            CorpusExcerpt(
                excerpt_id=f"excerpt-{index + 1:02d}",
                categories=categories,
                spoken_text=f"Testo {index + 1}.",
                notes="Testo sintetico revisionato.",
            )
        )
    return QualificationCorpus(excerpts=tuple(excerpts))


def candidate(engine: CandidateEngine) -> TtsCandidateConfig:
    voice_id = f"{engine}-voice"
    return TtsCandidateConfig(
        engine=engine,
        backend="stdlib",
        model_id=f"tests/{engine}",
        model=ModelIdentity(engine=engine, revision="test-v1"),
        model_license=(
            LicenseMetadata(
                spdx_identifier="MIT",
                source_url="https://example.test/model/LICENSE",
            )
            if engine != "fake"
            else None
        ),
        voice=VoiceConfig(voice_id=voice_id),
        settings=SynthesisSettings(sample_rate_hz=8_000, seed=17),
        inference_parameters={"test_mode": True},
    )


def fake_for(config: TtsCandidateConfig) -> FakeTtsEngine:
    return FakeTtsEngine(
        model=config.model,
        sample_rate_hz=config.settings.sample_rate_hz,
        voice_id=config.voice.voice_id,
    )


class PartialEngine:
    def __init__(self, delegate: FakeTtsEngine) -> None:
        self.delegate = delegate

    @property
    def capabilities(self) -> TtsCapabilities:
        return self.delegate.capabilities

    def health(self) -> TtsHealth:
        return self.delegate.health()

    def synthesize(self, request: TtsRequest) -> TtsResult:
        if request.spoken_text == "Testo 5.":
            raise RuntimeError("simulated sample failure")
        return self.delegate.synthesize(request)


def run_fake(
    root: Path,
    engine: CandidateEngine = "fake",
    candidate_name: str | None = None,
) -> tuple[TtsCandidateConfig, Path]:
    config = candidate(engine)
    name = candidate_name or engine
    summary = run_qualification(
        fake_for(config),
        config,
        small_corpus(),
        root,
        candidate_name=name,
    )
    return config, root / "work" / "tts-qualification" / name / summary.result_path


def test_full_fake_runner_writes_valid_wavs_result_and_compact_report(tmp_path: Path) -> None:
    config, result_path = run_fake(tmp_path)
    result = load_qualification_result(result_path)
    report = result_path.with_name("summary.md").read_text(encoding="utf-8")

    assert result.status == "completed"
    assert result.candidate_name == "fake"
    assert len(result.samples) == 24
    assert result.candidate == config
    assert result.total_audio_seconds > 0
    assert result.total_generation_seconds >= 0
    assert all(sample.real_time_factor is not None for sample in result.samples)
    assert all(
        (result_path.parent / sample.wav_path).is_file()
        for sample in result.samples
        if sample.wav_path is not None
    )
    assert "## Exceptions" in report
    assert "- None." in report
    assert "excerpt-01" not in report
    assert result_path.read_bytes().endswith(b"\n")


def test_runner_continues_after_one_sample_failure_and_removes_stale_wav(
    tmp_path: Path,
) -> None:
    config = candidate("fake")
    output = tmp_path / "work" / "tts-qualification" / "fake"
    stale = output / "audio" / "excerpt-05.wav"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")
    summary = run_qualification(
        PartialEngine(fake_for(config)),
        config,
        small_corpus(),
        tmp_path,
        candidate_name="fake",
    )
    result = load_qualification_result(output / summary.result_path)

    assert summary.status == "partial"
    assert summary.failure_count == 1
    assert result.samples[4].failure is not None
    assert result.samples[5].status == "completed"
    assert not stale.exists()
    report = render_qualification_report(result)
    assert "excerpt-05" in report
    assert "simulated sample failure" in report
    assert "excerpt-06" not in report


def test_runner_rejects_capability_health_and_sample_rate_mismatches(tmp_path: Path) -> None:
    config = candidate("fake")
    wrong_identity = candidate("kokoro")
    with pytest.raises(QualificationError, match="capabilities do not match"):
        run_qualification(
            fake_for(wrong_identity),
            config,
            small_corpus(),
            tmp_path,
            candidate_name="fake",
        )

    wrong_rate = config.model_copy(
        update={"settings": SynthesisSettings(sample_rate_hz=24_000, seed=17)}
    )
    with pytest.raises(QualificationError, match="sample rate"):
        run_qualification(
            fake_for(config),
            wrong_rate,
            small_corpus(),
            tmp_path,
            candidate_name="fake",
        )

    class UnhealthyEngine(PartialEngine):
        def health(self) -> TtsHealth:
            report = super().health()
            return report.model_copy(update={"healthy": False, "detail": "model unavailable"})

    with pytest.raises(QualificationError, match="model unavailable"):
        run_qualification(
            UnhealthyEngine(fake_for(config)),
            config,
            small_corpus(),
            tmp_path,
            candidate_name="fake",
        )


def test_listening_package_is_deterministic_and_keeps_mapping_separate(
    tmp_path: Path,
) -> None:
    _, first_result = run_fake(tmp_path / "source-a", "fake")
    _, second_result = run_fake(tmp_path / "source-b", "kokoro")
    first_output = tmp_path / "listening-a"
    second_output = tmp_path / "listening-b"

    first = prepare_listening_package((second_result, first_result), first_output, seed=99)
    second = prepare_listening_package((first_result, second_result), second_output, seed=99)
    first_mapping = (first_output / first.mapping_path).read_bytes()
    rating = (first_output / first.rating_sheet_path).read_text(encoding="utf-8")

    assert first.clip_count == 48
    assert first_mapping == (second_output / second.mapping_path).read_bytes()
    assert (first_output / first.rating_sheet_path).read_bytes() == (
        second_output / second.rating_sheet_path
    ).read_bytes()
    assert "fake" not in rating
    assert "kokoro" not in rating
    assert "excerpt-01" not in rating
    assert "clip-001" in rating
    mapping = json.loads(first_mapping)
    assert {clip["candidate_name"] for clip in mapping["clips"]} == {"fake", "kokoro"}


def test_qualify_tts_resolves_named_variant_configurations(tmp_path: Path) -> None:
    config_root = tmp_path / "config" / "qualification"
    config_root.mkdir(parents=True)
    shutil.copy(ROOT / "config" / "qualification" / "corpus.yaml", config_root)
    (config_root / "fake-fast.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "tts-candidate/v1",
                "engine": "fake",
                "backend": "stdlib",
                "model_id": "bilbo-tts/fake",
                "model": {"engine": "fake", "revision": "fake-v1"},
                "voice": {"voice_id": "fake-voice"},
                "settings": {"sample_rate_hz": 24_000, "seed": 99},
                "inference_parameters": {"variant": "fast"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = qualify_tts("fake-fast", tmp_path)
    result_path = tmp_path / "work" / "tts-qualification" / "fake-fast" / summary.result_path
    result = load_qualification_result(result_path)

    assert summary.candidate_name == "fake-fast"
    assert summary.engine == "fake"
    assert summary.status == "completed"
    assert result.candidate_name == "fake-fast"
    assert result.candidate.inference_parameters == {"variant": "fast"}

    with pytest.raises(QualificationError, match="invalid candidate name"):
        qualify_tts("../escape", tmp_path)


def test_variants_of_one_engine_qualify_and_blind_compare_side_by_side(tmp_path: Path) -> None:
    _, baseline_result = run_fake(tmp_path, "fake", candidate_name="fake")
    _, variant_result = run_fake(tmp_path, "fake", candidate_name="fake-fast")

    baseline = load_qualification_result(baseline_result)
    variant = load_qualification_result(variant_result)
    summary = prepare_listening_package(
        (baseline_result, variant_result),
        tmp_path / "listening",
        seed=7,
    )
    mapping = json.loads((tmp_path / "listening" / summary.mapping_path).read_bytes())

    assert baseline.candidate_name == "fake"
    assert variant.candidate_name == "fake-fast"
    assert baseline.engine == variant.engine == "fake"
    assert baseline_result.parent != variant_result.parent
    assert summary.candidate_count == 2
    assert {clip["candidate_name"] for clip in mapping["clips"]} == {"fake", "fake-fast"}

    with pytest.raises(QualificationError, match="distinct candidate names"):
        prepare_listening_package(
            (baseline_result, baseline_result),
            tmp_path / "duplicate",
            seed=7,
        )


def test_listening_rejects_incomplete_mismatched_and_corrupt_inputs(tmp_path: Path) -> None:
    _, first_result = run_fake(tmp_path / "source-a", "fake")
    _, second_result = run_fake(tmp_path / "source-b", "kokoro")
    with pytest.raises(QualificationError, match="at least two"):
        prepare_listening_package((first_result,), tmp_path / "one", seed=1)

    payload = json.loads(second_result.read_bytes())
    payload["corpus_sha256"] = "a" * 64
    second_result.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(QualificationError, match="different corpus checksums"):
        prepare_listening_package((first_result, second_result), tmp_path / "mismatch", seed=1)

    _, second_result = run_fake(tmp_path / "source-b", "kokoro")
    second = load_qualification_result(second_result)
    wav_path = second_result.parent / str(second.samples[0].wav_path)
    wav_path.write_bytes(b"corrupt")
    with pytest.raises(QualificationError, match="checksum mismatch"):
        prepare_listening_package((first_result, second_result), tmp_path / "corrupt", seed=1)


def test_result_loader_reports_missing_invalid_and_wrong_shape(tmp_path: Path) -> None:
    with pytest.raises(QualificationError, match="cannot read"):
        load_qualification_result(tmp_path / "missing.json")
    path = tmp_path / "result.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(QualificationError, match="invalid JSON"):
        load_qualification_result(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(QualificationError, match="must contain a JSON object"):
        load_qualification_result(path)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(QualificationError, match="invalid qualification result"):
        load_qualification_result(path)
