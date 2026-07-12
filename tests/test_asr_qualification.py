from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bilbo_tts.asr import MODEL_ID, MODEL_REVISION, MlxWhisperDependencies
from bilbo_tts.qualification.asr import (
    AsrQualificationResult,
    score_tts_asr,
)
from bilbo_tts.qualification.candidates import fake_candidate
from bilbo_tts.qualification.corpus import (
    CorpusCategory,
    QualificationCorpus,
    default_corpus_path,
    load_corpus,
)
from bilbo_tts.qualification.results import QualificationError
from bilbo_tts.qualification.runner import run_qualification
from bilbo_tts.serialization import sha256_bytes
from bilbo_tts.tts import FakeTtsEngine

ROOT = Path(__file__).parents[1]


def _prepared_project(
    tmp_path: Path,
    candidate_name: str = "fake",
) -> tuple[QualificationCorpus, Path]:
    config_root = tmp_path / "config" / "qualification"
    config_root.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "config" / "qualification" / "corpus.yaml", config_root)
    shutil.copy(ROOT / "config" / "qualification" / "asr.yaml", config_root)
    corpus = load_corpus(default_corpus_path(tmp_path))
    candidate = fake_candidate()
    engine = FakeTtsEngine(
        model=candidate.model,
        sample_rate_hz=candidate.settings.sample_rate_hz,
        voice_id=candidate.voice.voice_id,
    )
    run_qualification(engine, candidate, corpus, tmp_path, candidate_name=candidate_name)
    return corpus, tmp_path / "work" / "tts-qualification" / candidate_name / "result.json"


def test_scorer_resolves_pin_once_transcribes_full_corpus_sequentially_and_reports(
    tmp_path: Path,
) -> None:
    corpus, source_result_path = _prepared_project(tmp_path)
    excerpts = {excerpt.excerpt_id: excerpt for excerpt in corpus.excerpts}
    snapshot_calls: list[dict[str, object]] = []
    transcription_calls: list[tuple[str, dict[str, object]]] = []

    def snapshot_download(**kwargs: object) -> str:
        snapshot_calls.append(kwargs)
        return "/cache/pinned-whisper"

    def transcribe(path: str, **kwargs: object) -> object:
        transcription_calls.append((path, kwargs))
        excerpt = excerpts[Path(path).stem]
        transcript = excerpt.spoken_text
        if excerpt.excerpt_id == "prose-01":
            transcript = transcript.replace("mattina", "sera")
        return {"text": transcript}

    summary = score_tts_asr(
        "fake",
        tmp_path,
        dependencies=MlxWhisperDependencies(snapshot_download, transcribe),
    )

    output_root = tmp_path / "work" / "tts-qualification" / "asr" / "fake"
    result_bytes = (output_root / summary.result_path).read_bytes()
    result = AsrQualificationResult.model_validate(json.loads(result_bytes))
    report_bytes = (output_root / summary.report_path).read_bytes()

    assert summary.status == "completed"
    assert snapshot_calls == [{"repo_id": MODEL_ID, "revision": MODEL_REVISION}]
    assert [Path(path).stem for path, _ in transcription_calls] == [
        excerpt.excerpt_id for excerpt in corpus.excerpts
    ]
    assert all(
        kwargs
        == {
            "path_or_hf_repo": "/cache/pinned-whisper",
            "language": "it",
            "task": "transcribe",
            "temperature": 0.0,
            "fp16": True,
            "verbose": None,
            "word_timestamps": False,
        }
        for _, kwargs in transcription_calls
    )
    assert all("initial_prompt" not in kwargs for _, kwargs in transcription_calls)
    assert result.asr.model_id == MODEL_ID
    assert result.asr.revision == MODEL_REVISION
    assert result.samples[0].reference == excerpts["prose-01"].spoken_text
    assert result.samples[0].transcript is not None
    assert "sera" in result.samples[0].transcript
    assert result.overall.wer.substitutions == 1
    assert result.by_engine["fake"] == result.overall
    assert result.by_category[CorpusCategory.ORDINARY_PROSE].wer.substitutions == 1
    assert result.source_tts_result_sha256 == sha256_bytes(source_result_path.read_bytes())
    assert summary.result_sha256 == sha256_bytes(result_bytes)
    assert summary.report_sha256 == sha256_bytes(report_bytes)
    assert result_bytes.endswith(b"\n")
    report = report_bytes.decode("utf-8")
    assert "prose-01" in report
    assert "prose-02" not in report


def test_scorer_accepts_named_variants_and_rejects_mismatched_directories(
    tmp_path: Path,
) -> None:
    corpus, variant_result_path = _prepared_project(tmp_path, candidate_name="fake-fast")
    excerpts = {excerpt.excerpt_id: excerpt for excerpt in corpus.excerpts}

    def transcribe(path: str, **_kwargs: object) -> object:
        return {"text": excerpts[Path(path).stem].spoken_text}

    summary = score_tts_asr(
        "fake-fast",
        tmp_path,
        dependencies=MlxWhisperDependencies(lambda **_kwargs: "/snapshot", transcribe),
    )
    output = tmp_path / "work" / "tts-qualification" / "asr" / "fake-fast"
    result = AsrQualificationResult.model_validate(
        json.loads((output / summary.result_path).read_bytes())
    )

    assert summary.status == "completed"
    assert summary.candidate_name == "fake-fast"
    assert summary.engine == "fake"
    assert result.candidate_name == "fake-fast"
    assert result.by_engine["fake"] == result.overall

    misplaced = tmp_path / "work" / "tts-qualification" / "fake-other"
    shutil.copytree(variant_result_path.parent, misplaced)
    with pytest.raises(QualificationError, match="does not match requested"):
        score_tts_asr(
            "fake-other",
            tmp_path,
            dependencies=MlxWhisperDependencies(lambda **_kwargs: "/snapshot", transcribe),
        )


def test_scorer_records_partial_failure_and_continues_sequentially(tmp_path: Path) -> None:
    corpus, _ = _prepared_project(tmp_path)
    excerpts = {excerpt.excerpt_id: excerpt for excerpt in corpus.excerpts}
    called: list[str] = []

    def transcribe(path: str, **_kwargs: object) -> object:
        excerpt_id = Path(path).stem
        called.append(excerpt_id)
        if excerpt_id == "percent-01":
            raise RuntimeError("simulated decoder failure")
        return {"text": excerpts[excerpt_id].spoken_text}

    summary = score_tts_asr(
        "fake",
        tmp_path,
        dependencies=MlxWhisperDependencies(lambda **_kwargs: "/snapshot", transcribe),
    )

    output = tmp_path / "work" / "tts-qualification" / "asr" / "fake"
    result = AsrQualificationResult.model_validate(
        json.loads((output / summary.result_path).read_bytes())
    )
    failed = next(sample for sample in result.samples if sample.excerpt_id == "percent-01")
    report = (output / summary.report_path).read_text(encoding="utf-8")

    assert summary.status == "partial"
    assert summary.failure_count == 1
    assert called == [excerpt.excerpt_id for excerpt in corpus.excerpts]
    assert failed.failure is not None
    assert "simulated decoder failure" in failed.failure.message
    assert result.overall.failure_count == 1
    assert result.by_category[CorpusCategory.PERCENTAGES].failure_count == 1
    assert "percent-01" in report
    assert "simulated decoder failure" in report


def test_scorer_validates_every_wav_before_snapshot_or_transcription(tmp_path: Path) -> None:
    _, source_result_path = _prepared_project(tmp_path)
    source = json.loads(source_result_path.read_bytes())
    final_sample = source["samples"][-1]
    wav_path = source_result_path.parent / final_sample["wav_path"]
    wav_path.write_bytes(b"corrupt")
    calls: list[str] = []

    def snapshot_download(**_kwargs: object) -> str:
        calls.append("snapshot")
        return "/snapshot"

    def transcribe(_path: str, **_kwargs: object) -> object:
        calls.append("transcribe")
        return {"text": ""}

    with pytest.raises(QualificationError, match="checksum mismatch"):
        score_tts_asr(
            "fake",
            tmp_path,
            dependencies=MlxWhisperDependencies(snapshot_download, transcribe),
        )

    assert calls == []


def test_scorer_rejects_incomplete_result_before_loading_model(tmp_path: Path) -> None:
    _, source_result_path = _prepared_project(tmp_path)
    source = json.loads(source_result_path.read_bytes())
    source["samples"] = source["samples"][:-1]
    source_result_path.write_text(json.dumps(source), encoding="utf-8")
    calls: list[str] = []

    def snapshot_download(**_kwargs: object) -> str:
        calls.append("snapshot")
        return "/snapshot"

    with pytest.raises(QualificationError, match="invalid qualification result"):
        score_tts_asr(
            "fake",
            tmp_path,
            dependencies=MlxWhisperDependencies(
                snapshot_download,
                lambda _path, **_kwargs: {"text": ""},
            ),
        )

    assert calls == []
