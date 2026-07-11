"""Resumable book synthesis with validated content-addressed outputs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import Field

from bilbo_tts.artifacts import ArtifactError, ArtifactStore
from bilbo_tts.chunk_service import CHUNK_MANIFEST_PATH
from bilbo_tts.config import SynthesisConfig, VoiceConfig
from bilbo_tts.models import (
    ChunkManifest,
    ChunkRecord,
    ContractModel,
    GenerationFailure,
    GenerationManifest,
    GenerationRecord,
    NonEmptyText,
    NormalizedDocument,
    Sha256,
    SynthesisIdentity,
    SynthesisSettings,
    VoiceIdentity,
)
from bilbo_tts.normalization.service import NORMALIZED_PATH
from bilbo_tts.qualification.audio import (
    AudioValidationError,
    pcm_wav_bytes,
    validate_wav_bytes,
)
from bilbo_tts.qualification.candidates import TtsCandidateConfig
from bilbo_tts.serialization import sha256_bytes
from bilbo_tts.stages import load_stage_context
from bilbo_tts.tts import TtsEngine, TtsRequest
from bilbo_tts.tts.factory import (
    backend_identity,
    create_tts_engine,
    resolve_book_candidate,
)
from bilbo_tts.tts.validation import validate_result

GENERATION_MANIFEST_PATH = "manifests/generation-manifest.json"
SYNTHESIS_REPORT_PATH = "reports/synthesis.md"

EngineFactory = Callable[[TtsCandidateConfig, Path], TtsEngine]


class SynthesisError(ValueError):
    """A book cannot be synthesized from its current inputs."""


class SynthesizeSummary(ContractModel):
    """Machine-readable result emitted by the synthesize stage."""

    schema_version: Literal["synthesize-summary/v1"] = "synthesize-summary/v1"
    status: Literal["completed", "partial", "failed"]
    book_id: NonEmptyText
    chunk_manifest_sha256: Sha256
    selected_count: int = Field(ge=0)
    generated_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    generation_manifest_path: NonEmptyText
    generation_manifest_sha256: Sha256
    report_path: NonEmptyText
    report_sha256: Sha256


def synthesize_book(
    config_path: Path,
    project_root: Path,
    *,
    chapter: str | None = None,
    chunk_start: int | None = None,
    chunk_end: int | None = None,
    failed_only: bool = False,
    force: bool = False,
    engine_factory: EngineFactory = create_tts_engine,
) -> SynthesizeSummary:
    """Generate selected chunks while retaining every valid current output."""

    context = load_stage_context(config_path, project_root)
    store = context.workspace.artifacts
    normalized = store.read(NORMALIZED_PATH, NormalizedDocument)
    normalized_reference = store.reference(NORMALIZED_PATH)
    chunks = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    chunk_reference = store.reference(CHUNK_MANIFEST_PATH)
    _validate_upstream(context.config.book_id, normalized, normalized_reference.sha256, chunks)

    candidate = resolve_book_candidate(context.config.synthesis, context.workspace.project_root)
    identities = {
        chunk.chunk_id: _synthesis_identity(chunk, normalized, context.config.synthesis, candidate)
        for chunk in chunks.chunks
    }
    current = {
        chunk.chunk_id: _read_current_state(store, chunk, identities[chunk.chunk_id])
        for chunk in chunks.chunks
    }
    selected = _select_chunks(
        chunks,
        current,
        chapter=chapter,
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        failed_only=failed_only,
    )
    pending = [chunk for chunk in selected if force or current[chunk.chunk_id][0] is None]

    generated_count = 0
    run_failures: list[GenerationFailure] = []
    if pending:
        engine = engine_factory(candidate, context.book_dir)
        _validate_engine(engine, candidate)
        for chunk in pending:
            identity = identities[chunk.chunk_id]
            result = _generate_chunk(
                store,
                engine,
                chunk,
                identity,
                context.config.synthesis.voice,
                context.config.synthesis.settings,
                context.config.synthesis.max_retries,
            )
            if isinstance(result, GenerationRecord):
                generated_count += 1
            else:
                run_failures.append(result)

    refreshed = {
        chunk.chunk_id: _read_current_state(store, chunk, identities[chunk.chunk_id])
        for chunk in chunks.chunks
    }
    records = tuple(
        record for chunk in chunks.chunks if (record := refreshed[chunk.chunk_id][0]) is not None
    )
    failures = tuple(
        failure
        for chunk in chunks.chunks
        if refreshed[chunk.chunk_id][0] is None
        and (failure := refreshed[chunk.chunk_id][1]) is not None
    )
    missing = tuple(
        chunk.chunk_id for chunk in chunks.chunks if refreshed[chunk.chunk_id] == (None, None)
    )
    manifest = GenerationManifest(
        book_id=chunks.book_id,
        chunk_manifest_sha256=chunk_reference.sha256,
        records=records,
        failures=failures,
        missing_chunk_ids=missing,
    )
    manifest_reference = store.write(
        GENERATION_MANIFEST_PATH,
        manifest,
        dependencies=(chunk_reference,),
    )
    report_reference = store.write_bytes(
        SYNTHESIS_REPORT_PATH,
        render_synthesis_report(manifest).encode("utf-8"),
    )
    failed_count = len(run_failures)
    status: Literal["completed", "partial", "failed"] = (
        "completed"
        if failed_count == 0
        else "partial"
        if generated_count + len(selected) - len(pending) > 0
        else "failed"
    )
    return SynthesizeSummary(
        status=status,
        book_id=chunks.book_id,
        chunk_manifest_sha256=chunk_reference.sha256,
        selected_count=len(selected),
        generated_count=generated_count,
        skipped_count=len(selected) - len(pending),
        failed_count=failed_count,
        missing_count=len(missing),
        generation_manifest_path=manifest_reference.path,
        generation_manifest_sha256=manifest_reference.sha256,
        report_path=report_reference.path,
        report_sha256=report_reference.sha256,
    )


def render_synthesis_report(manifest: GenerationManifest) -> str:
    """Render current synthesis completeness and actionable failures."""

    total = len(manifest.records) + len(manifest.failures) + len(manifest.missing_chunk_ids)
    lines = [
        f"# Synthesis report: {manifest.book_id}",
        "",
        f"- Current chunks: {total}",
        f"- Valid WAVs: {len(manifest.records)}",
        f"- Failed chunks: {len(manifest.failures)}",
        f"- Missing chunks: {len(manifest.missing_chunk_ids)}",
        "",
        "## Failures",
        "",
    ]
    if manifest.failures:
        lines.extend(
            f"- `{failure.chunk_id}` after {failure.attempt_count} "
            f"attempt{'s' if failure.attempt_count != 1 else ''}: "
            f"{failure.exception_type}: {failure.message}"
            for failure in manifest.failures
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Missing chunks", ""])
    if manifest.missing_chunk_ids:
        lines.extend(f"- `{chunk_id}`" for chunk_id in manifest.missing_chunk_ids)
    else:
        lines.append("- None.")
    return "\n".join(lines).rstrip() + "\n"


def _validate_upstream(
    book_id: str,
    normalized: NormalizedDocument,
    normalized_sha256: str,
    chunks: ChunkManifest,
) -> None:
    if normalized.book_id != book_id or chunks.book_id != book_id:
        raise SynthesisError(f"synthesis artifacts do not belong to configured book {book_id!r}")
    if chunks.normalized_document_sha256 != normalized_sha256:
        raise SynthesisError(
            "chunk manifest does not reference the current normalized document; rerun chunk"
        )


def _synthesis_identity(
    chunk: ChunkRecord,
    normalized: NormalizedDocument,
    synthesis: SynthesisConfig,
    candidate: TtsCandidateConfig,
) -> SynthesisIdentity:
    return SynthesisIdentity(
        spoken_text=chunk.spoken_text,
        normalization_version=normalized.normalization_version,
        model=candidate.model,
        backend=backend_identity(candidate),
        voice=VoiceIdentity(
            voice_id=synthesis.voice.voice_id,
            reference_sha256=synthesis.voice.reference_sha256,
        ),
        settings=synthesis.settings,
    )


def _select_chunks(
    manifest: ChunkManifest,
    current: dict[
        str,
        tuple[GenerationRecord | None, GenerationFailure | None],
    ],
    *,
    chapter: str | None,
    chunk_start: int | None,
    chunk_end: int | None,
    failed_only: bool,
) -> list[ChunkRecord]:
    if chunk_start is not None and chunk_start < 0:
        raise SynthesisError("chunk start must be zero or greater")
    if chunk_end is not None and chunk_end < 0:
        raise SynthesisError("chunk end must be zero or greater")
    if chunk_start is not None and chunk_end is not None and chunk_start > chunk_end:
        raise SynthesisError("chunk start must not exceed chunk end")
    if manifest.chunks:
        maximum = manifest.chunks[-1].sequence
        if chunk_start is not None and chunk_start > maximum:
            raise SynthesisError(f"chunk start {chunk_start} exceeds maximum sequence {maximum}")
        if chunk_end is not None and chunk_end > maximum:
            raise SynthesisError(f"chunk end {chunk_end} exceeds maximum sequence {maximum}")
    elif chunk_start is not None or chunk_end is not None:
        raise SynthesisError("cannot select a chunk range from an empty manifest")
    chapter_ids = {chunk.chapter_id for chunk in manifest.chunks}
    if chapter is not None and chapter not in chapter_ids:
        raise SynthesisError(f"chapter {chapter!r} does not exist in the chunk manifest")

    selected = []
    for chunk in manifest.chunks:
        if chapter is not None and chunk.chapter_id != chapter:
            continue
        if chunk_start is not None and chunk.sequence < chunk_start:
            continue
        if chunk_end is not None and chunk.sequence > chunk_end:
            continue
        record, failure = current[chunk.chunk_id]
        if failed_only and (record is not None or failure is None):
            continue
        selected.append(chunk)
    return selected


def _validate_engine(engine: TtsEngine, candidate: TtsCandidateConfig) -> None:
    capabilities = engine.capabilities
    if capabilities.engine != candidate.engine or capabilities.model != candidate.model:
        raise SynthesisError("TTS engine capabilities do not match the pinned candidate")
    health = engine.health()
    if health.engine != candidate.engine or health.model != candidate.model:
        raise SynthesisError("TTS engine health identity does not match the pinned candidate")
    if not health.healthy:
        raise SynthesisError(f"{candidate.engine} health check failed: {health.detail}")


def _generate_chunk(
    store: ArtifactStore,
    engine: TtsEngine,
    chunk: ChunkRecord,
    identity: SynthesisIdentity,
    voice: VoiceConfig,
    settings: SynthesisSettings,
    max_retries: int,
) -> GenerationRecord | GenerationFailure:
    cache_key = identity.cache_key()
    wav_path, sidecar_path, failure_path = _generation_paths(chunk.chunk_id, cache_key)
    last_error: Exception | None = None
    for retry_number in range(max_retries + 1):
        try:
            request = TtsRequest(
                spoken_text=chunk.spoken_text,
                voice=voice,
                settings=settings,
            )
            result = engine.synthesize(request)
            validate_result(engine.capabilities, request, result)
            wav_data = pcm_wav_bytes(result)
            audio = validate_wav_bytes(
                wav_data,
                expected_sample_rate_hz=settings.sample_rate_hz,
            )
            record = GenerationRecord(
                chunk_id=chunk.chunk_id,
                chunk_content_sha256=chunk.content_sha256,
                identity=identity,
                cache_key=cache_key,
                output_path=wav_path,
                output_sha256=sha256_bytes(wav_data),
                sample_rate_hz=audio.sample_rate_hz,
                frame_count=audio.frame_count,
                duration_ms=max(1, round(audio.duration_seconds * 1000)),
                retry_number=retry_number,
            )
            store.write_bytes(wav_path, wav_data)
            store.write(sidecar_path, record)
            store.resolve(failure_path).unlink(missing_ok=True)
            return record
        except Exception as error:
            last_error = error
    assert last_error is not None
    failure = GenerationFailure(
        chunk_id=chunk.chunk_id,
        chunk_content_sha256=chunk.content_sha256,
        identity=identity,
        cache_key=cache_key,
        attempt_count=max_retries + 1,
        exception_type=type(last_error).__name__,
        message=str(last_error) or repr(last_error),
    )
    store.write(failure_path, failure)
    return failure


def _read_current_state(
    store: ArtifactStore,
    chunk: ChunkRecord,
    identity: SynthesisIdentity,
) -> tuple[GenerationRecord | None, GenerationFailure | None]:
    cache_key = identity.cache_key()
    wav_path, sidecar_path, failure_path = _generation_paths(chunk.chunk_id, cache_key)
    try:
        record = store.read(sidecar_path, GenerationRecord)
        if (
            record.chunk_id != chunk.chunk_id
            or record.chunk_content_sha256 != chunk.content_sha256
            or record.identity != identity
            or record.cache_key != cache_key
            or record.output_path != wav_path
        ):
            raise SynthesisError("generation sidecar does not match the current chunk")
        wav_data = store.resolve(wav_path).read_bytes()
        if sha256_bytes(wav_data) != record.output_sha256:
            raise SynthesisError("generation WAV checksum does not match its sidecar")
        audio = validate_wav_bytes(
            wav_data,
            expected_sample_rate_hz=identity.settings.sample_rate_hz,
        )
        if (
            audio.sample_rate_hz != record.sample_rate_hz
            or audio.frame_count != record.frame_count
            or max(1, round(audio.duration_seconds * 1000)) != record.duration_ms
        ):
            raise SynthesisError("generation WAV metadata does not match its sidecar")
        return record, None
    except (ArtifactError, AudioValidationError, OSError, SynthesisError):
        pass

    try:
        failure = store.read(failure_path, GenerationFailure)
        if (
            failure.chunk_id != chunk.chunk_id
            or failure.chunk_content_sha256 != chunk.content_sha256
            or failure.identity != identity
            or failure.cache_key != cache_key
        ):
            raise SynthesisError("generation failure does not match the current chunk")
        return None, failure
    except (ArtifactError, SynthesisError):
        return None, None


def _generation_paths(chunk_id: str, cache_key: str) -> tuple[str, str, str]:
    base = f"audio/{chunk_id}/{cache_key}"
    return f"{base}.wav", f"{base}.json", f"failures/{chunk_id}/{cache_key}.json"
