from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.models import BreakKind, ChunkManifest, ChunkRecord, PauseMetadata
from bilbo_tts.verification import VerifySummary
from bilbo_tts.verification_process import run_verification_loop


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project"
    book_dir = root / "books" / "book"
    book_dir.mkdir(parents=True)
    config = {
        "schema_version": "book-config/v1",
        "book_id": "book",
        "language": "it",
        "input": {"format": "latex", "path": "source/book.tex"},
        "metadata": {"title": "Libro", "author": "Autrice"},
        "normalization": {"version": "it-v1", "lexicons": []},
        "chunking": {"max_characters": 160},
        "synthesis": {"model_config_path": "config/qualification/fake.yaml"},
        "verification": {
            "model_config_path": "config/qualification/asr.yaml",
            "max_auto_retries": 2,
        },
    }
    config_path = book_dir / "book.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    candidate_path = root / "config" / "qualification" / "fake.yaml"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(
        "\n".join(
            [
                "schema_version: tts-candidate/v1",
                "engine: fake",
                "backend: stdlib",
                "model_id: bilbo-tts/fake",
                "model:",
                "  engine: fake",
                "  revision: fake-v1",
                "voice:",
                "  voice_id: fake-voice",
                "settings:",
                "  sample_rate_hz: 24000",
                "  seed: 7",
                "",
            ]
        ),
        encoding="utf-8",
    )
    store = ArtifactStore(root / "work" / "book")
    store.write(
        "manifests/chunk-manifest.json",
        ChunkManifest(
            book_id="book",
            normalized_document_sha256="a" * 64,
            chunks=tuple(
                ChunkRecord.create(
                    chunk_id=f"chunk-{index}",
                    chapter_id=f"chapter-{index:04d}",
                    paragraph_id=f"paragraph-{index}",
                    sentence_id=f"sentence-{index}",
                    sequence=index - 1,
                    display_text=f"Capitolo {index}.",
                    spoken_text=f"Capitolo {index}.",
                    pause=PauseMetadata(
                        break_before=BreakKind.CHAPTER,
                        duration_ms=100,
                    ),
                )
                for index in (1, 2)
            ),
        ),
    )
    return config_path, root


def _summary(status: str) -> str:
    retryable = int(status == "retryable")
    review = int(status == "review")
    accepted = int(status == "completed")
    summary = VerifySummary(
        status=status,  # type: ignore[arg-type]
        book_id="book",
        selected_count=1,
        transcribed_count=1,
        reused_count=0,
        accepted_count=accepted,
        retryable_count=retryable,
        review_count=review,
        verification_manifest_path="manifests/verification-manifest.json",
        verification_manifest_sha256="a" * 64,
        report_path="reports/verification.md",
        report_sha256="b" * 64,
    )
    return json.dumps(summary.model_dump(mode="json"))


def test_loop_exits_asr_before_starting_one_tts_retry_process(tmp_path: Path) -> None:
    config_path, root = _project(tmp_path)
    outputs = [_summary("retryable"), "{}", _summary("completed")]
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=outputs.pop(0), stderr="")

    result = run_verification_loop(
        config_path,
        root,
        chapters=("chapter-0001", "chapter-0002"),
        command_runner=run,
        pixi_executable=tmp_path / "pixi",
    )

    assert result.status == "completed"
    assert commands[0][2:4] == ["-e", "asr"]
    assert "verify-pass" in commands[0]
    assert commands[1][2:4] == ["-e", "default"]
    assert "--verification-retry" in commands[1]
    assert commands[2][2:4] == ["-e", "asr"]
    assert all(
        [command[index + 1] for index, argument in enumerate(command) if argument == "--chapter"]
        == ["chapter-0001", "chapter-0002"]
        for command in commands
    )
