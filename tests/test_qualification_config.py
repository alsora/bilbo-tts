from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bilbo_tts.qualification.candidates import (
    CandidateConfigurationError,
    TtsCandidateConfig,
    candidate_path,
    fake_candidate,
    load_asr_candidate,
    load_tts_candidate,
)
from bilbo_tts.qualification.corpus import (
    REQUIRED_CATEGORIES,
    CorpusError,
    QualificationCorpus,
    default_corpus_path,
    load_corpus,
)
from bilbo_tts.tts import FakeTtsEngine
from bilbo_tts.tts.factory import create_tts_engine

ROOT = Path(__file__).parents[1]


def test_committed_corpus_is_stable_complete_and_reviewed() -> None:
    path = default_corpus_path(ROOT)
    first = load_corpus(path)
    second = load_corpus(path)

    assert first == second
    assert len(first.excerpts) == 24
    assert {category for excerpt in first.excerpts for category in excerpt.categories} == set(
        REQUIRED_CATEGORIES
    )
    text = " ".join(excerpt.spoken_text for excerpt in first.excerpts)
    assert "zero virgola venticinque" in text
    assert "zero virgola zero venticinque" in text
    assert "l’obiettivo;" in text
    assert all(excerpt.notes for excerpt in first.excerpts)


def test_corpus_rejects_duplicate_ids_missing_coverage_and_wrong_size() -> None:
    corpus = load_corpus(default_corpus_path(ROOT))
    payload = corpus.model_dump(mode="json")
    payload["excerpts"][1]["excerpt_id"] = payload["excerpts"][0]["excerpt_id"]
    with pytest.raises(ValidationError, match="must be unique"):
        QualificationCorpus.model_validate(payload)

    payload = corpus.model_dump(mode="json")
    payload["excerpts"] = payload["excerpts"][:-1]
    with pytest.raises(ValidationError):
        QualificationCorpus.model_validate(payload)

    payload = corpus.model_dump(mode="json")
    for excerpt in payload["excerpts"]:
        excerpt["categories"] = ["ordinary-prose"]
    with pytest.raises(ValidationError, match="missing required categories"):
        QualificationCorpus.model_validate(payload)


def test_corpus_loader_reports_missing_scalar_and_invalid_yaml(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="cannot read"):
        load_corpus(tmp_path / "missing.yaml")
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("- item\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="must contain a YAML mapping"):
        load_corpus(scalar)
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("excerpts: [", encoding="utf-8")
    with pytest.raises(CorpusError, match="invalid YAML"):
        load_corpus(invalid)


def test_committed_candidate_pins_and_backend_policy() -> None:
    chatterbox = load_tts_candidate(candidate_path(ROOT, "chatterbox"))
    kokoro = load_tts_candidate(candidate_path(ROOT, "kokoro"))
    asr = load_asr_candidate(candidate_path(ROOT, "asr"))

    assert chatterbox.backend == "pytorch-mps"
    assert chatterbox.model_id == "ResembleAI/chatterbox"
    assert chatterbox.model.revision == "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
    assert chatterbox.code_revision == "65b18437192794391a0308a8f705b1e33e633948"
    assert chatterbox.inference_parameters["t3_model"] == "v3"
    assert chatterbox.inference_parameters["cfg_weight"] == 0.5
    assert chatterbox.voice.reference_path is None
    assert kokoro.model_id == "mlx-community/Kokoro-82M-bf16"
    assert kokoro.voice.voice_id == "if_sara"
    assert kokoro.settings.temperature is None
    assert asr.model_id == "mlx-community/whisper-large-v3-turbo"
    assert asr.revision == "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"


def test_candidate_rejects_mismatched_identity_and_non_json_values() -> None:
    candidate = fake_candidate()
    payload = candidate.model_dump()
    payload["model"] = {"engine": "kokoro", "revision": "v1"}
    with pytest.raises(ValidationError, match="must match candidate"):
        TtsCandidateConfig.model_validate(payload)
    payload = candidate.model_dump()
    payload["inference_parameters"] = {"bad key": 1}
    with pytest.raises(ValidationError):
        TtsCandidateConfig.model_validate(payload)
    payload = candidate.model_dump()
    payload["inference_parameters"] = {"value": float("nan")}
    with pytest.raises(ValidationError):
        TtsCandidateConfig.model_validate(payload)


def test_candidate_loaders_report_file_yaml_shape_and_schema_errors(tmp_path: Path) -> None:
    with pytest.raises(CandidateConfigurationError, match="cannot read"):
        load_tts_candidate(tmp_path / "missing.yaml")
    malformed = tmp_path / "candidate.yaml"
    malformed.write_text("model: [", encoding="utf-8")
    with pytest.raises(CandidateConfigurationError, match="invalid YAML"):
        load_tts_candidate(malformed)
    malformed.write_text("- item\n", encoding="utf-8")
    with pytest.raises(CandidateConfigurationError, match="must be a YAML mapping"):
        load_tts_candidate(malformed)
    malformed.write_text(yaml.safe_dump({"engine": "fake"}), encoding="utf-8")
    with pytest.raises(CandidateConfigurationError, match="invalid TTS candidate"):
        load_tts_candidate(malformed)
    with pytest.raises(CandidateConfigurationError, match="invalid ASR candidate"):
        load_asr_candidate(malformed)


def test_factory_constructs_fake_and_real_adapters_lazily() -> None:
    engine = create_tts_engine(fake_candidate())
    assert isinstance(engine, FakeTtsEngine)

    chatterbox = load_tts_candidate(candidate_path(ROOT, "chatterbox"))
    real_engine = create_tts_engine(chatterbox, ROOT)
    assert real_engine.capabilities.engine == "chatterbox"
