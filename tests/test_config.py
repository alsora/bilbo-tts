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
from bilbo_tts.models import BlockKind

HASH_A = "a" * 64


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
        "chunking": {"max_characters": 300},
        "synthesis": {
            "model_config_path": "config/qualification/kokoro-nicola-s120.yaml",
            "max_retries": 2,
        },
        "verification": {
            "model_config_path": "config/qualification/asr.yaml",
            "max_auto_retries": 2,
            "thresholds": {
                "max_wer": 0.45,
                "max_cer": 0.30,
                "max_missing_prefix_words": 1,
                "max_missing_suffix_words": 1,
                "max_repeated_ngram_count": 0,
                "max_silence_ratio": 0.95,
                "max_clipped_sample_ratio": 0.001,
                "min_speaking_rate_wpm": 70,
                "max_speaking_rate_wpm": 260,
            },
        },
        "assembly": {
            "pauses": {
                "clause_ms": 150,
                "sentence_ms": 250,
                "paragraph_ms": 600,
                "chapter_ms": 1500,
            },
            "loudness_lufs": -18,
            "true_peak_db": -2,
            "loudness_tolerance_lu": 0.5,
            "true_peak_tolerance_db": 0.5,
            "aac_bitrate_kbps": 64,
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
    assert config.ingestion.exclude_block_kinds == ()
    assert config.chunking.max_characters == 300
    assert config.synthesis.model_config_path == "config/qualification/kokoro-nicola-s120.yaml"
    assert config.verification.max_auto_retries == 2
    assert config.verification.thresholds.max_wer == 0.45
    assert config.assembly.pauses.clause_ms == 150
    assert config.assembly.loudness_tolerance_lu == 0.5
    assert config.assembly.true_peak_tolerance_db == 0.5
    assert config.assembly.aac_bitrate_kbps == 64
    assert BookConfig.model_validate_json(config.model_dump_json()) == config


def test_ingestion_can_exclude_supplementary_block_kinds() -> None:
    payload = valid_config()
    payload["ingestion"] = {
        "exclude_block_kinds": ["footnote", "table", "caption"],
    }

    config = BookConfig.model_validate(payload)

    assert config.ingestion.exclude_block_kinds == (
        BlockKind.FOOTNOTE,
        BlockKind.TABLE,
        BlockKind.CAPTION,
    )


@pytest.mark.parametrize(
    "kinds, message",
    [
        (["paragraph"], "supports only caption, footnote, and table"),
        (["table", "table"], "must not contain duplicates"),
    ],
)
def test_ingestion_rejects_unsupported_or_duplicate_exclusions(
    kinds: list[str], message: str
) -> None:
    payload = valid_config()
    payload["ingestion"] = {"exclude_block_kinds": kinds}

    with pytest.raises(ValidationError, match=message):
        BookConfig.model_validate(payload)


@pytest.mark.parametrize(
    "path",
    [
        "/absolute/candidate.yaml",
        "../outside/candidate.yaml",
        "config/qualification/candidate.json",
    ],
)
def test_model_config_path_must_be_a_relative_yaml_file(path: str) -> None:
    payload = valid_config()
    payload["synthesis"] = {"model_config_path": path}

    with pytest.raises(ValidationError, match="path must"):
        BookConfig.model_validate(payload)


def test_verification_thresholds_are_strict_and_ordered() -> None:
    payload = valid_config()
    payload["verification"] = {
        "model_config_path": "config/qualification/asr.json",
        "thresholds": {"min_speaking_rate_wpm": 300, "max_speaking_rate_wpm": 200},
    }

    with pytest.raises(ValidationError, match="YAML"):
        BookConfig.model_validate(payload)

    payload["verification"] = {
        "model_config_path": "config/qualification/asr.yaml",
        "thresholds": {"min_speaking_rate_wpm": 300, "max_speaking_rate_wpm": 200},
    }
    with pytest.raises(ValidationError, match="minimum speaking rate"):
        BookConfig.model_validate(payload)


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


def test_lexicon_scope_defaults_to_book_and_disambiguates_paths() -> None:
    book = LexiconConfig(path="overlay.yaml", sha256=HASH_A)
    shared = LexiconConfig(path="overlay.yaml", sha256=HASH_A, scope="shared")

    assert book.scope == "book"
    config = NormalizationConfig(version="v1", lexicons=(book, shared))
    assert [lexicon.scope for lexicon in config.lexicons] == ["book", "shared"]
    with pytest.raises(ValidationError, match="must be unique"):
        NormalizationConfig(version="v1", lexicons=(shared, shared))


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
