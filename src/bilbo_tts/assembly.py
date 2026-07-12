"""Verified chunk assembly, loudness normalization, and M4B validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from bilbo_tts.artifacts import ArtifactError, ArtifactStore
from bilbo_tts.chunk_service import CHUNK_MANIFEST_PATH
from bilbo_tts.ingest.service import DOCUMENT_PATH
from bilbo_tts.models import (
    AssemblyInputRecord,
    AssemblyManifest,
    BookDocument,
    ChapterMarker,
    ChunkManifest,
    ChunkRecord,
    ContractModel,
    GenerationManifest,
    GenerationRecord,
    LoudnessMeasurement,
    MediaCommand,
    NonEmptyText,
    ProbedMedia,
    ReviewStatus,
    Sha256,
    VerificationManifest,
)
from bilbo_tts.qualification.audio import AudioValidationError, validate_wav_file
from bilbo_tts.serialization import canonical_sha256, sha256_bytes
from bilbo_tts.stages import load_stage_context
from bilbo_tts.synthesis import GENERATION_MANIFEST_PATH
from bilbo_tts.verification import VERIFICATION_MANIFEST_PATH

ASSEMBLY_MANIFEST_PATH = "manifests/assembly-manifest.json"
ASSEMBLY_REPORT_PATH = "reports/assembly.md"
_LRA_TARGET = 11.0
_DURATION_TOLERANCE_MS = 100

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class AssemblyError(ValueError):
    """Current artifacts cannot be assembled into valid final media."""


class AssembleSummary(ContractModel):
    """Machine-readable result emitted by the assemble stage."""

    schema_version: Literal["assemble-summary/v1"] = "assemble-summary/v1"
    status: Literal["completed"]
    book_id: NonEmptyText
    selected_count: int = Field(gt=0)
    reused: bool
    output_path: NonEmptyText
    output_sha256: Sha256
    assembly_manifest_path: NonEmptyText
    assembly_manifest_sha256: Sha256
    report_path: NonEmptyText
    report_sha256: Sha256


def assemble_book(
    config_path: Path,
    project_root: Path,
    *,
    chapter: str | None = None,
    allow_unaccepted: bool = False,
    override_note: str | None = None,
    force: bool = False,
    command_runner: CommandRunner | None = None,
) -> AssembleSummary:
    """Assemble current verified chunks into one validated M4B."""

    if allow_unaccepted != bool(override_note and override_note.strip()):
        raise AssemblyError(
            "--allow-unaccepted and a non-empty --override-note are required together"
        )

    context = load_stage_context(config_path, project_root)
    store = context.workspace.artifacts
    document = store.read(DOCUMENT_PATH, BookDocument)
    document_reference = store.reference(DOCUMENT_PATH)
    chunks = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    chunk_reference = store.reference(CHUNK_MANIFEST_PATH)
    generations = store.read(GENERATION_MANIFEST_PATH, GenerationManifest)
    generation_reference = store.reference(GENERATION_MANIFEST_PATH)
    verification = store.read(VERIFICATION_MANIFEST_PATH, VerificationManifest)
    verification_reference = store.reference(VERIFICATION_MANIFEST_PATH)
    _validate_upstream(
        context.config.book_id,
        document,
        chunks,
        chunk_reference.sha256,
        generations,
        generation_reference.sha256,
        verification,
    )
    selected = _select_chunks(chunks, chapter)
    runner = command_runner or _run_command
    ffmpeg = _require_tool("ffmpeg")
    ffprobe = _require_tool("ffprobe")
    ffmpeg_version = _tool_version(ffmpeg, runner)
    ffprobe_version = _tool_version(ffprobe, runner)
    cover_path, cover_sha256 = _cover(context.book_dir, context.config.metadata.cover_path)

    inputs, sample_rate, unaccepted = _validate_inputs(
        store,
        selected,
        generations,
        verification,
        allow_unaccepted=allow_unaccepted,
    )
    assembly_input_sha256 = canonical_sha256(
        {
            "document": document_reference.sha256,
            "chunks": chunk_reference.sha256,
            "generations": generation_reference.sha256,
            "verification": verification_reference.sha256,
            "chapter": chapter,
            "metadata": context.config.metadata.model_dump(mode="json"),
            "assembly": context.config.assembly.model_dump(mode="json"),
            "cover_sha256": cover_sha256,
            "allow_unaccepted": allow_unaccepted,
            "override_note": override_note.strip() if override_note else None,
            "ffmpeg_version": ffmpeg_version,
            "ffprobe_version": ffprobe_version,
        }
    )
    output_path = _output_path(context.config.book_id, chapter)
    existing = (
        None
        if force
        else _load_reusable(
            store,
            output_path,
            assembly_input_sha256,
            chapter,
        )
    )
    if existing is not None:
        report_reference = store.write_bytes(
            ASSEMBLY_REPORT_PATH,
            render_assembly_report(existing).encode("utf-8"),
        )
        manifest_reference = store.reference(ASSEMBLY_MANIFEST_PATH)
        return _summary(existing, manifest_reference.sha256, report_reference.sha256, reused=True)

    output_target = store.resolve(output_path)
    output_target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".assembly-", dir=store.root) as temporary:
        staging = Path(temporary)
        pcm_path = staging / "input.wav"
        metadata_path = staging / "chapters.ffmeta"
        encoded_path = staging / "output.m4b"
        timeline_inputs, markers, total_frames = _write_pcm_timeline(
            pcm_path,
            store,
            selected,
            inputs,
            document,
            sample_rate,
        )
        metadata_path.write_text(
            _ffmetadata(context.config.metadata, markers, sample_rate),
            encoding="utf-8",
        )

        commands: list[MediaCommand] = []
        analysis_command = _analysis_command(
            ffmpeg,
            pcm_path,
            context.config.assembly.loudness_lufs,
            context.config.assembly.true_peak_db,
        )
        analysis_result = _checked(analysis_command, runner, "FFmpeg loudness analysis")
        analysis_raw = _parse_loudnorm_json(analysis_result.stderr)
        analysis = _measurement(analysis_raw, "analysis", "input")
        commands.append(
            _command_record(
                analysis_command,
                ffmpeg_version,
                staging,
                context.workspace.project_root,
            )
        )

        encode_command = _encode_command(
            ffmpeg,
            pcm_path,
            metadata_path,
            encoded_path,
            cover_path,
            context.config.assembly.loudness_lufs,
            context.config.assembly.true_peak_db,
            context.config.assembly.aac_bitrate_kbps,
            sample_rate,
            analysis_raw,
        )
        encode_result = _checked(encode_command, runner, "FFmpeg normalization and encode")
        normalization_raw = _parse_loudnorm_json(encode_result.stderr)
        normalization = _measurement(normalization_raw, "normalization", "output")
        commands.append(
            _command_record(
                encode_command,
                ffmpeg_version,
                staging,
                context.workspace.project_root,
            )
        )

        output_analysis_command = _analysis_command(
            ffmpeg,
            encoded_path,
            context.config.assembly.loudness_lufs,
            context.config.assembly.true_peak_db,
        )
        output_analysis_result = _checked(
            output_analysis_command,
            runner,
            "FFmpeg encoded-output loudness measurement",
        )
        output_raw = _parse_loudnorm_json(output_analysis_result.stderr)
        output_loudness = _measurement(output_raw, "output", "input")
        commands.append(
            _command_record(
                output_analysis_command,
                ffmpeg_version,
                staging,
                context.workspace.project_root,
            )
        )

        probe_command = _probe_command(ffprobe, encoded_path)
        probe_result = _checked(probe_command, runner, "FFprobe media validation")
        media, probed_chapters = _parse_probe(probe_result.stdout)
        commands.append(
            _command_record(
                probe_command,
                ffprobe_version,
                staging,
                context.workspace.project_root,
            )
        )
        _validate_media(
            media,
            probed_chapters,
            markers,
            total_frames,
            sample_rate,
            context.config.metadata.title,
            context.config.metadata.author,
            cover_path is not None,
            output_loudness,
            context.config.assembly.loudness_lufs,
            context.config.assembly.true_peak_db,
            context.config.assembly.loudness_tolerance_lu,
            context.config.assembly.true_peak_tolerance_db,
        )
        _promote(encoded_path, output_target)

    output_sha256 = _sha256_file(output_target)
    manifest = AssemblyManifest(
        book_id=context.config.book_id,
        scope_chapter_id=chapter,
        book_document_sha256=document_reference.sha256,
        chunk_manifest_sha256=chunk_reference.sha256,
        generation_manifest_sha256=generation_reference.sha256,
        verification_manifest_sha256=verification_reference.sha256,
        assembly_input_sha256=assembly_input_sha256,
        sample_rate_hz=sample_rate,
        total_frame_count=total_frames,
        inputs=timeline_inputs,
        chapters=markers,
        unaccepted_chunk_ids=tuple(unaccepted),
        override_note=override_note.strip() if override_note else None,
        commands=tuple(commands),
        loudness=(analysis, normalization, output_loudness),
        output_path=output_path,
        output_sha256=output_sha256,
        media=media,
    )
    report_reference = store.write_bytes(
        ASSEMBLY_REPORT_PATH,
        render_assembly_report(manifest).encode("utf-8"),
    )
    manifest_reference = store.write(
        ASSEMBLY_MANIFEST_PATH,
        manifest,
        dependencies=(
            document_reference,
            chunk_reference,
            generation_reference,
            verification_reference,
        ),
    )
    return _summary(manifest, manifest_reference.sha256, report_reference.sha256, reused=False)


def render_assembly_report(manifest: AssemblyManifest) -> str:
    """Render final-media evidence and any explicit acceptance override."""

    output = next(item for item in manifest.loudness if item.phase == "output")
    lines = [
        f"# Assembly report: {manifest.book_id}",
        "",
        f"- Scope: {manifest.scope_chapter_id or 'full book'}",
        f"- Chunks: {len(manifest.inputs)}",
        f"- Chapters: {len(manifest.chapters)}",
        f"- Duration: {manifest.media.duration_ms / 1000:.3f} seconds",
        f"- Audio: {manifest.media.codec_name}, mono, {manifest.media.sample_rate_hz} Hz",
        f"- Integrated loudness: {output.integrated_lufs:.2f} LUFS",
        f"- True peak: {output.true_peak_db:.2f} dBTP",
        f"- Cover art: {'yes' if manifest.media.cover_art else 'no'}",
        f"- Output: `{manifest.output_path}`",
        f"- Output SHA-256: `{manifest.output_sha256}`",
        "",
        "## Chapters",
        "",
    ]
    lines.extend(
        f"- `{chapter.chapter_id}` {chapter.title}: "
        f"{chapter.start_frame / manifest.sample_rate_hz:.3f}–"
        f"{chapter.end_frame / manifest.sample_rate_hz:.3f} seconds"
        for chapter in manifest.chapters
    )
    lines.extend(["", "## Acceptance override", ""])
    if manifest.unaccepted_chunk_ids:
        lines.append(f"- Note: {manifest.override_note}")
        lines.extend(f"- `{chunk_id}`" for chunk_id in manifest.unaccepted_chunk_ids)
    else:
        lines.append("- None; every included chunk was accepted.")
    return "\n".join(lines).rstrip() + "\n"


def _validate_upstream(
    book_id: str,
    document: BookDocument,
    chunks: ChunkManifest,
    chunk_sha256: str,
    generations: GenerationManifest,
    generation_sha256: str,
    verification: VerificationManifest,
) -> None:
    if {document.book_id, chunks.book_id, generations.book_id, verification.book_id} != {book_id}:
        raise AssemblyError(f"assembly artifacts do not belong to configured book {book_id!r}")
    if generations.chunk_manifest_sha256 != chunk_sha256:
        raise AssemblyError("generation manifest does not reference the current chunk manifest")
    if verification.generation_manifest_sha256 != generation_sha256:
        raise AssemblyError(
            "verification manifest does not reference the current generation manifest"
        )


def _select_chunks(manifest: ChunkManifest, chapter: str | None) -> list[ChunkRecord]:
    chapter_ids = {chunk.chapter_id for chunk in manifest.chunks}
    if chapter is not None and chapter not in chapter_ids:
        raise AssemblyError(f"chapter {chapter!r} does not exist in the chunk manifest")
    selected = [
        chunk for chunk in manifest.chunks if chapter is None or chunk.chapter_id == chapter
    ]
    if not selected:
        raise AssemblyError("assembly selection contains no chunks")
    return selected


def _validate_inputs(
    store: ArtifactStore,
    selected: Sequence[ChunkRecord],
    generations: GenerationManifest,
    verification: VerificationManifest,
    *,
    allow_unaccepted: bool,
) -> tuple[dict[str, GenerationRecord], int, list[str]]:
    generation_by_chunk = {record.chunk_id: record for record in generations.records}
    verification_by_chunk = {record.chunk_id: record for record in verification.records}
    inputs: dict[str, GenerationRecord] = {}
    unaccepted: list[str] = []
    sample_rate: int | None = None
    for chunk in selected:
        generation = generation_by_chunk.get(chunk.chunk_id)
        if generation is None:
            raise AssemblyError(
                f"chunk {chunk.chunk_id!r} lacks valid generated audio; run synthesize first"
            )
        if generation.chunk_content_sha256 != chunk.content_sha256:
            raise AssemblyError(f"chunk {chunk.chunk_id!r} generation is stale")
        wav_path = store.resolve(generation.output_path)
        try:
            metadata = validate_wav_file(
                wav_path,
                expected_sample_rate_hz=generation.sample_rate_hz,
            )
        except AudioValidationError as error:
            raise AssemblyError(f"chunk {chunk.chunk_id!r} WAV is invalid: {error}") from error
        if _sha256_file(wav_path) != generation.output_sha256:
            raise AssemblyError(f"chunk {chunk.chunk_id!r} WAV checksum does not match generation")
        if (
            metadata.frame_count != generation.frame_count
            or metadata.sample_rate_hz != generation.sample_rate_hz
        ):
            raise AssemblyError(f"chunk {chunk.chunk_id!r} WAV metadata does not match generation")
        if sample_rate is None:
            sample_rate = generation.sample_rate_hz
        elif sample_rate != generation.sample_rate_hz:
            raise AssemblyError("selected chunks do not share one sample rate")
        verified = verification_by_chunk.get(chunk.chunk_id)
        current_generation_sha256 = canonical_sha256(generation)
        if verified is not None and verified.generation_sha256 != current_generation_sha256:
            raise AssemblyError(
                f"chunk {chunk.chunk_id!r} verification is stale for its current generation"
            )
        accepted = verified is not None and verified.status is ReviewStatus.ACCEPTED
        if not accepted:
            if not allow_unaccepted:
                raise AssemblyError(
                    f"chunk {chunk.chunk_id!r} is not accepted for its current generation"
                )
            unaccepted.append(chunk.chunk_id)
        inputs[chunk.chunk_id] = generation
    assert sample_rate is not None
    return inputs, sample_rate, unaccepted


def _write_pcm_timeline(
    output_path: Path,
    store: ArtifactStore,
    selected: Sequence[ChunkRecord],
    generations: dict[str, GenerationRecord],
    document: BookDocument,
    sample_rate: int,
) -> tuple[tuple[AssemblyInputRecord, ...], tuple[ChapterMarker, ...], int]:
    titles = {chapter.chapter_id: chapter.title for chapter in document.chapters}
    records: list[AssemblyInputRecord] = []
    chapter_starts: list[tuple[str, str, int]] = []
    frame_cursor = 0
    current_chapter: str | None = None
    with wave.open(str(output_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.setcomptype("NONE", "not compressed")
        for chunk in selected:
            generation = generations[chunk.chunk_id]
            if chunk.chapter_id != current_chapter:
                try:
                    title = titles[chunk.chapter_id]
                except KeyError as error:
                    raise AssemblyError(
                        f"chunk references unknown chapter {chunk.chapter_id!r}"
                    ) from error
                chapter_starts.append((chunk.chapter_id, title, frame_cursor))
                current_chapter = chunk.chapter_id
            pause_frames = round(chunk.pause.duration_ms * sample_rate / 1000)
            records.append(
                AssemblyInputRecord(
                    chunk_id=chunk.chunk_id,
                    sequence=chunk.sequence,
                    generation_sha256=canonical_sha256(generation),
                    output_path=generation.output_path,
                    output_sha256=generation.output_sha256,
                    audio_frame_count=generation.frame_count,
                    pause_frame_count=pause_frames,
                    start_frame=frame_cursor,
                )
            )
            _write_silence(output, pause_frames)
            with wave.open(str(store.resolve(generation.output_path)), "rb") as source:
                while frames := source.readframes(65_536):
                    output.writeframesraw(frames)
            frame_cursor += pause_frames + generation.frame_count
        output.writeframes(b"")
    markers = tuple(
        ChapterMarker(
            chapter_id=chapter_id,
            title=title,
            start_frame=start,
            end_frame=(
                chapter_starts[index + 1][2] if index + 1 < len(chapter_starts) else frame_cursor
            ),
        )
        for index, (chapter_id, title, start) in enumerate(chapter_starts)
    )
    return tuple(records), markers, frame_cursor


def _write_silence(output: wave.Wave_write, frame_count: int) -> None:
    remaining = frame_count
    block = b"\0" * (65_536 * 2)
    while remaining:
        count = min(remaining, 65_536)
        output.writeframesraw(block[: count * 2])
        remaining -= count


def _analysis_command(ffmpeg: str, input_path: Path, loudness: float, peak: float) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-i",
        str(input_path),
        "-af",
        f"loudnorm=I={loudness}:TP={peak}:LRA={_LRA_TARGET}:print_format=json",
        "-f",
        "null",
        "-",
    ]


def _encode_command(
    ffmpeg: str,
    pcm_path: Path,
    metadata_path: Path,
    output_path: Path,
    cover_path: Path | None,
    loudness: float,
    peak: float,
    bitrate_kbps: int,
    sample_rate: int,
    measured: dict[str, Any],
) -> list[str]:
    filter_value = (
        f"loudnorm=I={loudness}:TP={peak}:LRA={_LRA_TARGET}"
        f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true:print_format=json"
    )
    command = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(pcm_path)]
    metadata_index = 1
    if cover_path is not None:
        command.extend(["-i", str(cover_path)])
        metadata_index = 2
    command.extend(["-f", "ffmetadata", "-i", str(metadata_path), "-map", "0:a:0"])
    if cover_path is not None:
        command.extend(
            [
                "-map",
                "1:v:0",
                "-c:v",
                "mjpeg",
                "-disposition:v:0",
                "attached_pic",
            ]
        )
    else:
        command.append("-vn")
    command.extend(
        [
            "-map_metadata",
            str(metadata_index),
            "-map_chapters",
            str(metadata_index),
            "-af",
            filter_value,
            "-c:a",
            "aac",
            "-b:a",
            f"{bitrate_kbps}k",
            "-ar",
            str(sample_rate),
            "-movflags",
            "+faststart",
            "-f",
            "ipod",
            str(output_path),
        ]
    )
    return command


def _probe_command(ffprobe: str, output_path: Path) -> list[str]:
    return [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        str(output_path),
    ]


def _ffmetadata(metadata: Any, chapters: Sequence[ChapterMarker], sample_rate: int) -> str:
    values = {
        "title": metadata.title,
        "artist": metadata.author,
        "album": metadata.title,
        "album_artist": metadata.author,
    }
    if metadata.subtitle:
        values["description"] = metadata.subtitle
    if metadata.narrator:
        values["composer"] = metadata.narrator
    lines = [";FFMETADATA1", *(f"{key}={_escape_metadata(value)}" for key, value in values.items())]
    for chapter in chapters:
        lines.extend(
            [
                "[CHAPTER]",
                f"TIMEBASE=1/{sample_rate}",
                f"START={chapter.start_frame}",
                f"END={chapter.end_frame}",
                f"title={_escape_metadata(chapter.title)}",
            ]
        )
    return "\n".join(lines) + "\n"


def _escape_metadata(value: str) -> str:
    return re.sub(r"([\\=;#])", r"\\\1", value).replace("\n", "\\\n")


def _parse_loudnorm_json(stderr: str) -> dict[str, Any]:
    for candidate in reversed(re.findall(r"\{.*?\}", stderr, flags=re.DOTALL)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "input_i" in parsed and "output_i" in parsed:
            return parsed
    raise AssemblyError("FFmpeg did not emit a valid loudnorm JSON measurement")


def _measurement(
    values: dict[str, Any],
    phase: Literal["analysis", "normalization", "output"],
    prefix: Literal["input", "output"],
) -> LoudnessMeasurement:
    try:
        return LoudnessMeasurement(
            phase=phase,
            integrated_lufs=float(values[f"{prefix}_i"]),
            true_peak_db=float(values[f"{prefix}_tp"]),
            loudness_range_lu=float(values[f"{prefix}_lra"]),
            threshold_lufs=float(values[f"{prefix}_thresh"]),
            target_offset_lu=float(values["target_offset"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AssemblyError(f"invalid FFmpeg loudnorm measurement: {error}") from error


def _parse_probe(stdout: str) -> tuple[ProbedMedia, list[tuple[int, int]]]:
    try:
        payload = json.loads(stdout)
        streams = payload["streams"]
        format_data = payload["format"]
        chapters = payload.get("chapters", [])
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise AssemblyError(f"invalid FFprobe JSON: {error}") from error
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(audio) != 1:
        raise AssemblyError(f"final media must contain exactly one audio stream, got {len(audio)}")
    try:
        duration_ms = round(float(format_data["duration"]) * 1000)
        tags = {str(key).lower(): str(value) for key, value in format_data.get("tags", {}).items()}
        ranges = [
            (round(float(item["start_time"]) * 1000), round(float(item["end_time"]) * 1000))
            for item in chapters
        ]
        media = ProbedMedia(
            codec_name=str(audio[0]["codec_name"]),
            channels=int(audio[0]["channels"]),
            sample_rate_hz=int(audio[0]["sample_rate"]),
            duration_ms=duration_ms,
            tags=tags,
            cover_art=any(
                stream.get("codec_type") == "video"
                and stream.get("disposition", {}).get("attached_pic") == 1
                for stream in streams
            ),
            chapter_count=len(chapters),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AssemblyError(f"incomplete FFprobe media metadata: {error}") from error
    return media, ranges


def _validate_media(
    media: ProbedMedia,
    probed_chapters: Sequence[tuple[int, int]],
    expected_chapters: Sequence[ChapterMarker],
    total_frames: int,
    sample_rate: int,
    title: str,
    author: str,
    expect_cover: bool,
    output_loudness: LoudnessMeasurement,
    target_loudness: float,
    target_peak: float,
    loudness_tolerance: float,
    peak_tolerance: float,
) -> None:
    expected_duration_ms = round(total_frames * 1000 / sample_rate)
    if media.codec_name != "aac" or media.channels != 1 or media.sample_rate_hz != sample_rate:
        raise AssemblyError("final media audio must be mono AAC at the assembled PCM sample rate")
    if abs(media.duration_ms - expected_duration_ms) > _DURATION_TOLERANCE_MS:
        raise AssemblyError(
            f"final duration {media.duration_ms} ms differs from expected "
            f"{expected_duration_ms} ms by more than {_DURATION_TOLERANCE_MS} ms"
        )
    if media.tags.get("title") != title or media.tags.get("artist") != author:
        raise AssemblyError("final media title or author metadata is missing or incorrect")
    if media.cover_art != expect_cover:
        raise AssemblyError("final media cover-art presence does not match configuration")
    if len(probed_chapters) != len(expected_chapters):
        raise AssemblyError("final media chapter count does not match the assembly timeline")
    for probed, expected in zip(probed_chapters, expected_chapters, strict=True):
        expected_range = (
            round(expected.start_frame * 1000 / sample_rate),
            round(expected.end_frame * 1000 / sample_rate),
        )
        if any(
            abs(actual - planned) > 1
            for actual, planned in zip(probed, expected_range, strict=True)
        ):
            raise AssemblyError("final media chapter timestamps do not match the assembly timeline")
    if abs(output_loudness.integrated_lufs - target_loudness) > loudness_tolerance:
        raise AssemblyError(
            f"integrated loudness {output_loudness.integrated_lufs:.2f} LUFS is outside "
            f"{target_loudness:.2f} ± {loudness_tolerance:.2f} LU"
        )
    if output_loudness.true_peak_db > target_peak + peak_tolerance:
        raise AssemblyError(
            f"true peak {output_loudness.true_peak_db:.2f} dBTP exceeds "
            f"{target_peak + peak_tolerance:.2f} dBTP"
        )


def _cover(book_dir: Path, relative_path: str | None) -> tuple[Path | None, str | None]:
    if relative_path is None:
        return None, None
    path = (book_dir / relative_path).resolve()
    if not path.is_relative_to(book_dir):
        raise AssemblyError("cover path escapes the configured book directory")
    try:
        data = path.read_bytes()
    except OSError as error:
        raise AssemblyError(f"cannot read configured cover {path}: {error}") from error
    if not data:
        raise AssemblyError(f"configured cover is empty: {path}")
    return path, sha256_bytes(data)


def _output_path(book_id: str, chapter: str | None) -> str:
    suffix = f"-{chapter}" if chapter else ""
    return f"media/{book_id}{suffix}.m4b"


def _load_reusable(
    store: ArtifactStore,
    output_path: str,
    assembly_input_sha256: str,
    chapter: str | None,
) -> AssemblyManifest | None:
    try:
        manifest = store.read(ASSEMBLY_MANIFEST_PATH, AssemblyManifest)
    except ArtifactError:
        return None
    if (
        manifest.assembly_input_sha256 != assembly_input_sha256
        or manifest.scope_chapter_id != chapter
        or manifest.output_path != output_path
    ):
        return None
    output = store.resolve(output_path)
    try:
        actual = _sha256_file(output)
    except AssemblyError:
        return None
    return manifest if actual == manifest.output_sha256 else None


def _summary(
    manifest: AssemblyManifest,
    manifest_sha256: str,
    report_sha256: str,
    *,
    reused: bool,
) -> AssembleSummary:
    return AssembleSummary(
        status="completed",
        book_id=manifest.book_id,
        selected_count=len(manifest.inputs),
        reused=reused,
        output_path=manifest.output_path,
        output_sha256=manifest.output_sha256,
        assembly_manifest_path=ASSEMBLY_MANIFEST_PATH,
        assembly_manifest_sha256=manifest_sha256,
        report_path=ASSEMBLY_REPORT_PATH,
        report_sha256=report_sha256,
    )


def _require_tool(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise AssemblyError(f"required media tool is unavailable: {name}")
    return resolved


def _tool_version(path: str, runner: CommandRunner) -> str:
    result = _checked([path, "-version"], runner, f"{Path(path).name} version check")
    first_line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    if not first_line:
        raise AssemblyError(f"{Path(path).name} did not report a version")
    return first_line


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, check=False, text=True)


def _checked(
    command: Sequence[str],
    runner: CommandRunner,
    operation: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(command)
    except OSError as error:
        raise AssemblyError(f"{operation} could not start: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise AssemblyError(f"{operation} failed with exit code {result.returncode}: {detail}")
    return result


def _command_record(
    command: Sequence[str],
    version: str,
    staging: Path,
    project_root: Path,
) -> MediaCommand:
    normalized = tuple(
        argument.replace(str(staging), "<staging>").replace(str(project_root), "<project>")
        for argument in command[1:]
    )
    return MediaCommand(
        tool="ffprobe" if Path(command[0]).name == "ffprobe" else "ffmpeg",
        version=version,
        argv=normalized,
    )


def _promote(source: Path, target: Path) -> None:
    try:
        with source.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(source, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        raise AssemblyError(f"cannot atomically publish final media {target}: {error}") from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
    except OSError as error:
        raise AssemblyError(f"cannot read media file {path}: {error}") from error
    return digest.hexdigest()
