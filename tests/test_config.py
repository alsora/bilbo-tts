from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bilbo_tts.config import (
    BookConfig,
    ConfigurationError,
    LexiconConfig,
    NormalizationConfig,
    VoiceConfig,
    load_book_config,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def valid_config() -> dict[str, object]:
    return {
        "schema_version": "book-config/v1",
        "book_id": "finance-book",
        "language": "it",
        "input": {"format": "latex", "path": "source/book.tex"},
        "metadata": {
            "title": "Finanza",
            "author": "Ada Autrice",
            "cover_path": "assets/cover.jpg",
        },
        "normalization": {
            "version": "it-v1",
            "lexicons": [
                {
                    "path": "config/finance-it.yaml",
                    "sha256": HASH_A,
                }
            ],
        },
        "synthesis": {
            "engine": "fake-engine",
            "model_revision": "revision-1",
            "voice": {
                "voice_id": "narrator",
                "reference_path": "voice/narrator.wav",
                "reference_sha256": HASH_B,
            },
            "settings": {
                "sample_rate_hz": 24000,
                "seed": 42,
                "speed": 1.0,
            },
            "max_retries": 2,
        },
        "assembly": {
            "pauses": {
                "sentence_ms": 250,
                "paragraph_ms": 600,
                "chapter_ms": 1500,
            },
            "loudness_lufs": -18,
            "true_peak_db": -2,
        },
    }


def write_config(path: Path, payload: object) -> None:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")


def test_load_valid_book_config(tmp_path: Path) -> None:
    path = tmp_path / "book.yaml"
    write_config(path, valid_config())

    config = load_book_config(path)

    assert config.book_id == "finance-book"
    assert config.input.path == "source/book.tex"
    assert config.synthesis.voice.reference_sha256 == HASH_B
    assert BookConfig.model_validate_json(config.model_dump_json()) == config


def test_unknown_and_incompatible_fields_are_rejected(tmp_path: Path) -> None:
    payload = valid_config()
    payload["mystery"] = True
    path = tmp_path / "unknown.yaml"
    write_config(path, payload)

    with pytest.raises(ConfigurationError, match="Extra inputs are not permitted"):
        load_book_config(path)

    incompatible = valid_config()
    incompatible["input"] = {"format": "pdf", "path": "source/book.tex"}
    write_config(path, incompatible)
    with pytest.raises(ConfigurationError, match="incompatible with pdf input"):
        load_book_config(path)


@pytest.mark.parametrize(
    "path",
    [
        "/absolute/book.tex",
        "../outside/book.tex",
        "source/../outside/book.tex",
        "./source/book.tex",
    ],
)
def test_source_paths_must_remain_in_book_directory(path: str) -> None:
    payload = valid_config()
    payload["input"] = {"format": "latex", "path": path}

    with pytest.raises(ValidationError, match="path must"):
        BookConfig.model_validate(payload)


def test_voice_reference_path_and_hash_are_required_together() -> None:
    with pytest.raises(ValidationError, match="must be provided together"):
        VoiceConfig(voice_id="narrator", reference_path="voice.wav")
    with pytest.raises(ValidationError, match="FLAC or WAV"):
        VoiceConfig(
            voice_id="narrator",
            reference_path="voice.mp3",
            reference_sha256=HASH_A,
        )


def test_lexicon_paths_must_be_unique_yaml_files() -> None:
    lexicon = LexiconConfig(path="finance.yaml", sha256=HASH_A)
    with pytest.raises(ValidationError, match="must be unique"):
        NormalizationConfig(version="v1", lexicons=(lexicon, lexicon))
    with pytest.raises(ValidationError, match="YAML"):
        LexiconConfig(path="finance.json", sha256=HASH_A)


def test_config_loader_reports_file_and_yaml_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigurationError, match="cannot read"):
        load_book_config(missing)

    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="must contain a YAML mapping"):
        load_book_config(scalar)

    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("metadata: [", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="invalid YAML"):
        load_book_config(malformed)
