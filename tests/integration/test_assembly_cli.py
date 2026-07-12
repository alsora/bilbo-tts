from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from typer.testing import CliRunner

from bilbo_tts import cli
from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.assembly import ASSEMBLY_MANIFEST_PATH
from bilbo_tts.chunk_service import CHUNK_MANIFEST_PATH
from bilbo_tts.models import AssemblyManifest, ChunkManifest, GenerationManifest
from bilbo_tts.synthesis import GENERATION_MANIFEST_PATH
from bilbo_tts.verification import verify_book_pass

FixtureRunner = Callable[[str, str], tuple[Any, Path]]


class _Transcriber:
    def __init__(self, transcripts: dict[str, str]) -> None:
        self.transcripts = transcripts

    def transcribe(self, wav_path: Path) -> str:
        return self.transcripts[wav_path.name]


@pytest.mark.parametrize("with_cover", [False, True])
def test_assemble_cli_creates_valid_idempotent_m4b(
    run_book_fixture: object,
    with_cover: bool,
) -> None:
    run = cast(FixtureRunner, run_book_fixture)
    for stage in ("ingest", "normalize", "chunk", "synthesize"):
        result, project_root = run("tiny-latex", stage)
        assert result.exit_code == 0, result.output

    store = ArtifactStore(project_root / "work" / "tiny-latex")
    chunks = store.read(CHUNK_MANIFEST_PATH, ChunkManifest)
    generations = store.read(GENERATION_MANIFEST_PATH, GenerationManifest)
    spoken = {chunk.chunk_id: chunk.spoken_text for chunk in chunks.chunks}
    transcripts = {
        Path(record.output_path).name: spoken[record.chunk_id] for record in generations.records
    }
    config_path = project_root / "books" / "tiny-latex" / "book.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["verification"]["thresholds"] = {
        "max_wer": 0.45,
        "max_cer": 0.30,
        "max_missing_prefix_words": 1,
        "max_missing_suffix_words": 1,
        "max_repeated_ngram_count": 0,
        "max_silence_ratio": 0.95,
        "max_clipped_sample_ratio": 0.001,
        "min_speaking_rate_wpm": 1,
        "max_speaking_rate_wpm": 2_000,
    }
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    if with_cover:
        cover_path = config_path.parent / "assets" / "cover.png"
        cover_path.parent.mkdir(parents=True)
        cover_path.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
                "+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
        )
        config["metadata"]["cover_path"] = "assets/cover.png"
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    asr_path = project_root / "config" / "qualification" / "asr.yaml"
    asr_path.parent.mkdir(parents=True)
    asr_path.write_text(
        "\n".join(
            [
                "schema_version: asr-candidate/v1",
                "engine: mlx-whisper",
                "backend: mlx",
                "model_id: test/whisper",
                "revision: test-revision",
                "language: it",
                "",
            ]
        ),
        encoding="utf-8",
    )
    verify_book_pass(
        config_path,
        project_root,
        transcriber_factory=lambda _config: _Transcriber(transcripts),
    )

    first, _ = run("tiny-latex", "assemble")
    assert first.exit_code == 0, first.output
    first_summary = json.loads(first.stdout)
    manifest = store.read(ASSEMBLY_MANIFEST_PATH, AssemblyManifest)
    output = store.resolve(manifest.output_path)
    first_mtime = output.stat().st_mtime_ns

    second, _ = run("tiny-latex", "assemble")
    assert second.exit_code == 0, second.output
    second_summary = json.loads(second.stdout)

    assert first_summary["status"] == "completed"
    assert first_summary["reused"] is False
    assert second_summary["reused"] is True
    assert output.stat().st_mtime_ns == first_mtime
    assert manifest.media.codec_name == "aac"
    assert manifest.media.channels == 1
    assert manifest.media.chapter_count == len(manifest.chapters)
    assert manifest.media.tags["title"] == "Piccolo libro LaTeX"
    assert manifest.media.cover_art is with_cover
    assert manifest.loudness[-1].phase == "output"

    if not with_cover:
        chapter_ids = tuple(dict.fromkeys(chunk.chapter_id for chunk in chunks.chunks))
        scope = chapter_ids[:2]
        scoped = CliRunner().invoke(
            cli.app,
            [
                "assemble",
                str(config_path),
                "--project-root",
                str(project_root),
                "--chapter",
                scope[0],
                "--chapter",
                scope[1],
            ],
        )
        assert scoped.exit_code == 0, scoped.output
        scoped_manifest = store.read(ASSEMBLY_MANIFEST_PATH, AssemblyManifest)
        assert scoped_manifest.schema_version == "assembly-manifest/v2"
        assert scoped_manifest.scope_chapter_ids == scope
        assert scoped_manifest.output_path == (f"media/tiny-latex-{scope[0]}-to-{scope[1]}.m4b")
        assert tuple(chapter.chapter_id for chapter in scoped_manifest.chapters) == scope
