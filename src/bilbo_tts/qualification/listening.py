"""Deterministic blind-listening package generation."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.models import ContractModel, Identifier, NonEmptyText, Sha256
from bilbo_tts.qualification.audio import validate_wav_bytes
from bilbo_tts.qualification.results import (
    QualificationError,
    QualificationResult,
    load_qualification_result,
)
from bilbo_tts.serialization import canonical_json_bytes, sha256_bytes

MAPPING_PATH = "mapping.json"
RATING_SHEET_PATH = "rating-sheet.md"


class BlindClip(ContractModel):
    """Unblinded identity for one opaque listening clip."""

    clip_id: Identifier
    audio_path: NonEmptyText
    excerpt_id: Identifier
    engine: Identifier
    wav_sha256: Sha256


class BlindListeningMapping(ContractModel):
    """Private mapping from opaque clips to source engines."""

    schema_version: Literal["tts-listening-mapping/v1"] = "tts-listening-mapping/v1"
    seed: int
    corpus_sha256: Sha256
    engines: tuple[Identifier, ...]
    clips: tuple[BlindClip, ...]

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> Self:
        clip_ids = [clip.clip_id for clip in self.clips]
        audio_paths = [clip.audio_path for clip in self.clips]
        if len(clip_ids) != len(set(clip_ids)):
            raise ValueError("blind clip identifiers must be unique")
        if len(audio_paths) != len(set(audio_paths)):
            raise ValueError("blind audio paths must be unique")
        return self


class ListeningPackageSummary(ContractModel):
    """Canonical machine-readable listening-package result."""

    schema_version: Literal["tts-listening-summary/v1"] = "tts-listening-summary/v1"
    status: Literal["completed"] = "completed"
    seed: int
    corpus_sha256: Sha256
    engine_count: int = Field(ge=2)
    excerpt_count: int = Field(gt=0)
    clip_count: int = Field(gt=0)
    mapping_path: NonEmptyText
    mapping_sha256: Sha256
    rating_sheet_path: NonEmptyText
    rating_sheet_sha256: Sha256


def prepare_listening_package(
    result_paths: tuple[Path, ...],
    output_root: Path,
    seed: int,
) -> ListeningPackageSummary:
    """Validate qualification evidence and write a blinded package."""

    if len(result_paths) < 2:
        raise QualificationError("blind listening requires at least two qualification results")
    loaded = sorted(
        ((path.expanduser().resolve(), load_qualification_result(path)) for path in result_paths),
        key=lambda item: item[1].engine,
    )
    _validate_compatible_results(tuple(result for _, result in loaded))
    store = ArtifactStore(output_root)
    rng = random.Random(seed)
    clips: list[BlindClip] = []
    reference = loaded[0][1]
    for excerpt_index, _reference_sample in enumerate(reference.samples, start=1):
        shuffled = list(loaded)
        rng.shuffle(shuffled)
        for engine_index, (result_path, result) in enumerate(shuffled):
            sample = result.samples[excerpt_index - 1]
            if sample.wav_path is None or sample.wav_sha256 is None:
                raise QualificationError(
                    f"{result.engine} excerpt {sample.excerpt_id} has no completed WAV"
                )
            source_store = ArtifactStore(result_path.parent)
            source_path = source_store.resolve(sample.wav_path)
            try:
                wav_data = source_path.read_bytes()
            except OSError as error:
                raise QualificationError(
                    f"cannot read qualification WAV {source_path}: {error}"
                ) from error
            actual_sha256 = sha256_bytes(wav_data)
            if actual_sha256 != sample.wav_sha256:
                raise QualificationError(
                    f"qualification WAV checksum mismatch for {result.engine} "
                    f"excerpt {sample.excerpt_id}"
                )
            validate_wav_bytes(
                wav_data,
                expected_sample_rate_hz=result.candidate.settings.sample_rate_hz,
            )
            clip_id = f"clip-{excerpt_index:03d}-{engine_index + 1:02d}"
            audio_path = f"audio/{clip_id}.wav"
            output_reference = store.write_bytes(audio_path, wav_data)
            clips.append(
                BlindClip(
                    clip_id=clip_id,
                    audio_path=output_reference.path,
                    excerpt_id=sample.excerpt_id,
                    engine=result.engine,
                    wav_sha256=output_reference.sha256,
                )
            )
    mapping = BlindListeningMapping(
        seed=seed,
        corpus_sha256=reference.corpus_sha256,
        engines=tuple(result.engine for _, result in loaded),
        clips=tuple(clips),
    )
    mapping_reference = store.write_bytes(
        MAPPING_PATH,
        canonical_json_bytes(mapping) + b"\n",
    )
    rating_reference = store.write_bytes(
        RATING_SHEET_PATH,
        render_rating_sheet(mapping).encode("utf-8"),
    )
    return ListeningPackageSummary(
        seed=seed,
        corpus_sha256=mapping.corpus_sha256,
        engine_count=len(mapping.engines),
        excerpt_count=len(reference.samples),
        clip_count=len(mapping.clips),
        mapping_path=mapping_reference.path,
        mapping_sha256=mapping_reference.sha256,
        rating_sheet_path=rating_reference.path,
        rating_sheet_sha256=rating_reference.sha256,
    )


def prepare_listening_for_engines(
    engines: tuple[str, ...],
    project_root: Path,
    seed: int,
) -> ListeningPackageSummary:
    """Resolve engine result files below the qualification workspace."""

    root = project_root.expanduser().resolve()
    result_paths = tuple(
        root / "work" / "tts-qualification" / engine / "result.json" for engine in engines
    )
    output_root = root / "work" / "tts-qualification" / "listening"
    return prepare_listening_package(result_paths, output_root, seed)


def render_rating_sheet(mapping: BlindListeningMapping) -> str:
    """Render rating prompts without engine or excerpt identities."""

    clips_per_excerpt = len(mapping.engines)
    lines = [
        "# Blind TTS listening rating sheet",
        "",
        (
            "Score every clip from one to five for intelligibility, pronunciation, "
            "prosody, voice consistency, artifacts, and overall preference."
        ),
        "Do not open mapping.json until every rating is recorded.",
        "",
    ]
    for excerpt_index in range(len(mapping.clips) // clips_per_excerpt):
        start = excerpt_index * clips_per_excerpt
        group = mapping.clips[start : start + clips_per_excerpt]
        lines.extend(
            [
                f"## Set {excerpt_index + 1:03d}",
                "",
                *(
                    f"- `{clip.clip_id}`: intelligibility __; pronunciation __; "
                    "prosody __; voice consistency __; artifacts __; overall __."
                    for clip in group
                ),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _validate_compatible_results(results: tuple[QualificationResult, ...]) -> None:
    engines = [result.engine for result in results]
    if len(engines) != len(set(engines)):
        raise QualificationError("qualification results must use distinct engines")
    reference = results[0]
    if not reference.samples:
        raise QualificationError("qualification results must contain a complete corpus")
    expected = tuple((sample.excerpt_id, sample.spoken_text_sha256) for sample in reference.samples)
    for result in results:
        if result.status != "completed":
            raise QualificationError(
                f"qualification result for {result.engine} is not complete: {result.status}"
            )
        if result.corpus_sha256 != reference.corpus_sha256:
            raise QualificationError("qualification results use different corpus checksums")
        actual = tuple((sample.excerpt_id, sample.spoken_text_sha256) for sample in result.samples)
        if actual != expected:
            raise QualificationError(
                "qualification results do not contain the same complete ordered corpus"
            )
