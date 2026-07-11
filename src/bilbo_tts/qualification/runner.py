"""Independent TTS qualification runner and compact report rendering."""

from __future__ import annotations

import resource
import sys
import time
from pathlib import Path
from typing import Literal

from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.models import VoiceIdentity
from bilbo_tts.qualification.audio import pcm_wav_bytes, validate_wav_bytes
from bilbo_tts.qualification.candidates import (
    TtsCandidateConfig,
    candidate_path,
    fake_candidate,
    load_tts_candidate,
)
from bilbo_tts.qualification.corpus import (
    CorpusExcerpt,
    QualificationCorpus,
    default_corpus_path,
    load_corpus,
)
from bilbo_tts.qualification.results import (
    QualificationError,
    QualificationFailure,
    QualificationResult,
    QualificationSample,
    TtsQualificationSummary,
)
from bilbo_tts.serialization import canonical_json_bytes, canonical_sha256, sha256_bytes
from bilbo_tts.tts import TtsEngine, TtsRequest
from bilbo_tts.tts.factory import create_tts_engine
from bilbo_tts.tts.validation import validate_result

RESULT_PATH = "result.json"
REPORT_PATH = "summary.md"


def qualify_tts(engine_name: str, project_root: Path) -> TtsQualificationSummary:
    """Load committed inputs and qualify one explicitly selected engine."""

    root = project_root.expanduser().resolve()
    candidate = (
        fake_candidate()
        if engine_name == "fake"
        else load_tts_candidate(candidate_path(root, engine_name))
    )
    if candidate.engine != engine_name:
        raise QualificationError(
            f"candidate engine {candidate.engine!r} does not match requested engine {engine_name!r}"
        )
    corpus = load_corpus(default_corpus_path(root))
    engine = create_tts_engine(candidate, root)
    return run_qualification(engine, candidate, corpus, root)


def run_qualification(
    engine: TtsEngine,
    candidate: TtsCandidateConfig,
    corpus: QualificationCorpus,
    project_root: Path,
) -> TtsQualificationSummary:
    """Run one engine across the full corpus and persist all evidence."""

    capabilities = engine.capabilities
    if capabilities.engine != candidate.engine or capabilities.model != candidate.model:
        raise QualificationError("engine capabilities do not match the candidate model identity")
    if capabilities.native_sample_rate_hz != candidate.settings.sample_rate_hz:
        raise QualificationError("engine native sample rate does not match candidate settings")
    health = engine.health()
    if health.engine != candidate.engine or health.model != candidate.model:
        raise QualificationError("engine health identity does not match candidate configuration")
    if not health.healthy:
        raise QualificationError(f"{candidate.engine} health check failed: {health.detail}")

    output_root = (
        project_root.expanduser().resolve() / "work" / "tts-qualification" / candidate.engine
    )
    store = ArtifactStore(output_root)
    samples = tuple(
        _qualify_excerpt(engine, candidate, store, excerpt) for excerpt in corpus.excerpts
    )
    failed_count = sum(sample.status == "failed" for sample in samples)
    status: Literal["completed", "partial", "failed"] = (
        "completed"
        if failed_count == 0
        else "failed"
        if failed_count == len(samples)
        else "partial"
    )
    result = QualificationResult(
        status=status,
        engine=candidate.engine,
        corpus_sha256=canonical_sha256(corpus),
        candidate=candidate,
        health=health,
        samples=samples,
        total_generation_seconds=sum(sample.generation_seconds for sample in samples),
        total_audio_seconds=sum(
            sample.audio.duration_seconds for sample in samples if sample.audio is not None
        ),
        process_peak_rss_bytes=_process_peak_rss_bytes(),
    )
    result_reference = store.write_bytes(
        RESULT_PATH,
        canonical_json_bytes(result) + b"\n",
    )
    report_reference = store.write_bytes(
        REPORT_PATH,
        render_qualification_report(result).encode("utf-8"),
    )
    return TtsQualificationSummary(
        status=result.status,
        engine=result.engine,
        corpus_sha256=result.corpus_sha256,
        sample_count=len(samples),
        completed_count=len(samples) - failed_count,
        failure_count=failed_count,
        result_path=result_reference.path,
        result_sha256=result_reference.sha256,
        report_path=report_reference.path,
        report_sha256=report_reference.sha256,
    )


def render_qualification_report(result: QualificationResult) -> str:
    """Render totals and exceptions without repeating every success."""

    completed = sum(sample.status == "completed" for sample in result.samples)
    failures = [sample for sample in result.samples if sample.failure is not None]
    lines = [
        f"# TTS qualification: {result.engine}",
        "",
        f"- Status: `{result.status}`.",
        f"- Corpus excerpts: {len(result.samples)}.",
        f"- Completed excerpts: {completed}.",
        f"- Failed excerpts: {len(failures)}.",
        f"- Generation time: {result.total_generation_seconds:.6f} seconds.",
        f"- Audio duration: {result.total_audio_seconds:.6f} seconds.",
        (
            f"- Process peak RSS: {result.process_peak_rss_bytes} bytes."
            if result.process_peak_rss_bytes is not None
            else "- Process peak RSS: unavailable on this platform."
        ),
        "",
        "## Exceptions",
        "",
    ]
    if not failures:
        lines.append("- None.")
    else:
        for sample in failures:
            assert sample.failure is not None
            lines.append(
                f"- `{sample.excerpt_id}`: {sample.failure.exception_type}: "
                f"{sample.failure.message}"
            )
    return "\n".join(lines).rstrip() + "\n"


def _qualify_excerpt(
    engine: TtsEngine,
    candidate: TtsCandidateConfig,
    store: ArtifactStore,
    excerpt: CorpusExcerpt,
) -> QualificationSample:
    request = TtsRequest(
        spoken_text=excerpt.spoken_text,
        voice=candidate.voice,
        settings=candidate.settings,
    )
    voice = VoiceIdentity(
        voice_id=candidate.voice.voice_id,
        reference_sha256=candidate.voice.reference_sha256,
    )
    wav_path = f"audio/{excerpt.excerpt_id}.wav"
    started = time.perf_counter()
    try:
        result = engine.synthesize(request)
        generation_seconds = time.perf_counter() - started
        validate_result(engine.capabilities, request, result)
        wav_data = pcm_wav_bytes(result)
        audio = validate_wav_bytes(
            wav_data,
            expected_sample_rate_hz=candidate.settings.sample_rate_hz,
        )
        reference = store.write_bytes(wav_path, wav_data)
        return QualificationSample(
            excerpt_id=excerpt.excerpt_id,
            categories=excerpt.categories,
            spoken_text_sha256=sha256_bytes(excerpt.spoken_text.encode("utf-8")),
            status="completed",
            model=candidate.model,
            voice=voice,
            settings=candidate.settings,
            inference_parameters=candidate.inference_parameters,
            generation_seconds=generation_seconds,
            wav_path=reference.path,
            wav_sha256=reference.sha256,
            audio=audio,
            real_time_factor=generation_seconds / audio.duration_seconds,
        )
    except Exception as error:
        generation_seconds = time.perf_counter() - started
        store.resolve(wav_path).unlink(missing_ok=True)
        return QualificationSample(
            excerpt_id=excerpt.excerpt_id,
            categories=excerpt.categories,
            spoken_text_sha256=sha256_bytes(excerpt.spoken_text.encode("utf-8")),
            status="failed",
            model=candidate.model,
            voice=voice,
            settings=candidate.settings,
            inference_parameters=candidate.inference_parameters,
            generation_seconds=generation_seconds,
            failure=QualificationFailure(
                exception_type=type(error).__name__,
                message=str(error) or repr(error),
            ),
        )


def _process_peak_rss_bytes() -> int | None:
    if sys.platform != "darwin":
        return None
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if peak > 0 else None
