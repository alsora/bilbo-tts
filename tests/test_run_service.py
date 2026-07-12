from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from bilbo_tts.artifacts import ArtifactStore
from bilbo_tts.assembly import AssembleSummary
from bilbo_tts.chunk_service import ChunkSummary
from bilbo_tts.ingest import IngestSummary
from bilbo_tts.models import (
    BlockKind,
    BookDocument,
    BreakKind,
    ChapterDocument,
    ChunkManifest,
    ChunkRecord,
    DocumentBlock,
    NormalizedBlock,
    NormalizedDocument,
    PauseMetadata,
    SourceFormat,
    SourceLocation,
)
from bilbo_tts.normalization import NormalizeSummary
from bilbo_tts.run_service import (
    RUN_REPORT_PATH,
    TEXT_ONLY_REPORT_PATH,
    RunError,
    RunSummary,
    TextOnlySummary,
    run_book,
)
from bilbo_tts.serialization import canonical_sha256
from bilbo_tts.synthesis import SynthesizeSummary
from bilbo_tts.verification import VerifySummary

HASH = "a" * 64


def _project(
    tmp_path: Path,
) -> tuple[Path, Path, IngestSummary, NormalizeSummary, ChunkSummary]:
    root = tmp_path / "project"
    book_dir = root / "books" / "book"
    source_dir = book_dir / "source"
    source_dir.mkdir(parents=True)
    (source_dir / "book.tex").write_text("test", encoding="utf-8")
    config = {
        "schema_version": "book-config/v1",
        "book_id": "book",
        "language": "it",
        "input": {"format": "latex", "path": "source/book.tex"},
        "metadata": {"title": "Libro", "author": "Autrice"},
        "normalization": {"version": "it-v1", "lexicons": []},
        "chunking": {"max_characters": 100},
        "synthesis": {"model_config_path": "config/qualification/fake.yaml"},
        "assembly": {
            "pauses": {
                "clause_ms": 100,
                "sentence_ms": 200,
                "paragraph_ms": 500,
                "chapter_ms": 1000,
            }
        },
    }
    config_path = book_dir / "book.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    chapters = tuple(
        ChapterDocument(
            chapter_id=f"chapter-{index}",
            order=index - 1,
            title=f"Capitolo {index}",
            blocks=(
                DocumentBlock(
                    block_id=f"block-{index}",
                    kind=BlockKind.PARAGRAPH,
                    display_text=f"Testo capitolo {index}.",
                    source=SourceLocation(
                        source_path="source/book.tex",
                        start_line=index,
                        end_line=index,
                    ),
                    warnings=("extract-review",) if index == 1 else (),
                ),
            ),
        )
        for index in (1, 2, 3)
    )
    document = BookDocument(
        book_id="book",
        source_format=SourceFormat.LATEX,
        source_sha256=HASH,
        chapters=chapters,
        warnings=("source-global-review",),
    )
    normalized = NormalizedDocument(
        book_id="book",
        book_document_sha256=canonical_sha256(document),
        normalization_version="it-v1",
        lexicon_sha256=HASH,
        blocks=(
            NormalizedBlock(
                block_id="block-1",
                display_text="Testo capitolo 1.",
                spoken_text="Testo breve capitolo uno.",
            ),
            NormalizedBlock(
                block_id="block-2",
                display_text="Testo capitolo 2.",
                spoken_text="Testo con # simbolo ancora irrisolto.",
                warnings=("unresolved-symbols: #",),
            ),
            NormalizedBlock(
                block_id="block-3",
                display_text="Testo capitolo 3.",
                spoken_text=("parola " * 15 + "fine").strip(),
            ),
        ),
    )
    chunks = ChunkManifest(
        book_id="book",
        normalized_document_sha256=canonical_sha256(normalized),
        chunks=(
            ChunkRecord.create(
                chunk_id="chunk-1",
                chapter_id="chapter-1",
                paragraph_id="block-1",
                sentence_id="sentence-1",
                sequence=0,
                display_text="Testo capitolo 1.",
                spoken_text="Testo breve capitolo uno.",
                pause=PauseMetadata(break_before=BreakKind.CHAPTER, duration_ms=1000),
            ),
            ChunkRecord.create(
                chunk_id="chunk-2a",
                chapter_id="chapter-2",
                paragraph_id="block-2",
                sentence_id="sentence-2",
                sequence=1,
                display_text="Testo capitolo 2.",
                spoken_text="Testo con # simbolo",
                pause=PauseMetadata(break_before=BreakKind.CHAPTER, duration_ms=1000),
            ),
            ChunkRecord.create(
                chunk_id="chunk-2b",
                chapter_id="chapter-2",
                paragraph_id="block-2",
                sentence_id="sentence-2",
                sequence=2,
                display_text="Testo capitolo 2.",
                spoken_text="ancora irrisolto.",
                pause=PauseMetadata(break_before=BreakKind.NONE, duration_ms=0),
            ),
            ChunkRecord.create(
                chunk_id="chunk-3",
                chapter_id="chapter-3",
                paragraph_id="block-3",
                sentence_id="sentence-3",
                sequence=3,
                display_text="Testo capitolo 3.",
                spoken_text=("parola " * 15 + "fine").strip(),
                pause=PauseMetadata(break_before=BreakKind.CHAPTER, duration_ms=1000),
            ),
        ),
    )
    store = ArtifactStore(root / "work" / "book")
    document_reference = store.write("manifests/book-document.json", document)
    normalized_reference = store.write(
        "manifests/normalized-document.json",
        normalized,
        dependencies=(document_reference,),
    )
    chunk_reference = store.write(
        "manifests/chunk-manifest.json",
        chunks,
        dependencies=(document_reference, normalized_reference),
    )
    ingest = IngestSummary(
        status="completed",
        book_id="book",
        source_format=SourceFormat.LATEX,
        source_sha256=HASH,
        document_path="manifests/book-document.json",
        document_sha256=document_reference.sha256,
        report_path="reports/extraction.md",
        report_sha256=HASH,
        chapter_count=3,
        block_count=3,
        warning_count=2,
    )
    normalize = NormalizeSummary(
        book_id="book",
        document_sha256=document_reference.sha256,
        normalized_path="manifests/normalized-document.json",
        normalized_sha256=normalized_reference.sha256,
        report_path="reports/normalization.md",
        report_sha256=HASH,
        block_count=3,
        transformation_count=0,
        lexicon_application_count=0,
        warning_count=1,
    )
    chunk = ChunkSummary(
        book_id="book",
        normalized_sha256=normalized_reference.sha256,
        chunk_manifest_path="manifests/chunk-manifest.json",
        chunk_manifest_sha256=chunk_reference.sha256,
        report_path="reports/chunking.md",
        report_sha256=HASH,
        chunk_count=4,
        max_characters=100,
        largest_chunk_characters=94,
    )
    return config_path, root, ingest, normalize, chunk


def _patch_text_stages(
    monkeypatch: pytest.MonkeyPatch,
    ingest: IngestSummary,
    normalize: NormalizeSummary,
    chunk: ChunkSummary,
    calls: list[str] | None = None,
) -> None:
    from bilbo_tts import run_service

    def record(name: str, value: object) -> Any:
        def stage(_config: Path, _root: Path) -> object:
            if calls is not None:
                calls.append(name)
            return value

        return stage

    monkeypatch.setattr(run_service, "ingest_book", record("ingest", ingest))
    monkeypatch.setattr(run_service, "normalize_book", record("normalize", normalize))
    monkeypatch.setattr(run_service, "chunk_book", record("chunk", chunk))


def _synthesis_summary(*, status: str = "completed", generated: int = 3) -> SynthesizeSummary:
    return SynthesizeSummary(
        status=status,  # type: ignore[arg-type]
        book_id="book",
        chunk_manifest_sha256=HASH,
        selected_count=3,
        generated_count=generated,
        skipped_count=3 - generated,
        failed_count=int(status != "completed"),
        missing_count=1,
        generation_manifest_path="manifests/generation-manifest.json",
        generation_manifest_sha256=HASH,
        report_path="reports/synthesis.md",
        report_sha256=HASH,
    )


def _verify_summary(status: str = "completed") -> VerifySummary:
    return VerifySummary(
        status=status,  # type: ignore[arg-type]
        book_id="book",
        selected_count=3,
        transcribed_count=3,
        reused_count=0,
        accepted_count=3 if status == "completed" else 2,
        retryable_count=int(status == "retryable"),
        review_count=int(status == "review"),
        verification_manifest_path="manifests/verification-manifest.json",
        verification_manifest_sha256=HASH,
        report_path="reports/verification.md",
        report_sha256=HASH,
    )


def _assembly_summary(*, reused: bool = False) -> AssembleSummary:
    return AssembleSummary(
        status="completed",
        book_id="book",
        selected_count=3,
        reused=reused,
        output_path="media/book-chapter-1-to-chapter-2.m4b",
        output_sha256=HASH,
        assembly_manifest_path="manifests/assembly-manifest.json",
        assembly_manifest_sha256=HASH,
        report_path="reports/assembly.md",
        report_sha256=HASH,
    )


def test_text_only_qualifies_selected_scope_and_is_byte_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, root, ingest, normalize, chunk = _project(tmp_path)
    calls: list[str] = []
    _patch_text_stages(monkeypatch, ingest, normalize, chunk, calls)

    first = run_book(
        config_path,
        root,
        chapters=("chapter-1", "chapter-2"),
        text_only=True,
    )
    report_path = root / "work" / "book" / TEXT_ONLY_REPORT_PATH
    first_report = report_path.read_bytes()
    second = run_book(
        config_path,
        root,
        chapters=("chapter-1", "chapter-2"),
        text_only=True,
    )

    assert isinstance(first, TextOnlySummary)
    assert first == second
    assert calls == ["ingest", "normalize", "chunk"] * 2
    assert tuple((chapter.chapter_id, chapter.title) for chapter in first.chapters) == (
        ("chapter-1", "Capitolo 1"),
        ("chapter-2", "Capitolo 2"),
    )
    assert (first.chapter_count, first.block_count, first.chunk_count) == (2, 2, 3)
    assert first.word_count == 9
    assert first.extraction_warning_count == 2
    assert first.extraction_warnings == ("source-global-review", "extract-review")
    assert first.normalization_warning_count == 1
    assert first.normalization_warnings == ("unresolved-symbols: #",)
    assert first.unresolved_token_count == 1
    assert first.unresolved_tokens == ("#",)
    assert first.chunk_outlier_count == len(first.chunk_outlier_ids)
    assert first.forced_split_count == 1
    assert first.forced_split_sentence_ids == ("sentence-2",)
    assert first.estimated_speech_rate_wpm == 150
    assert first.estimated_speech_duration_ms == 3600
    assert first.configured_pause_duration_ms == 2000
    assert first.estimated_total_duration_ms == 5600
    assert report_path.read_bytes() == first_report
    report = first_report.decode()
    assert "Capitolo 1" in report
    assert "150 words per minute" in report
    assert "source-global-review" in report
    assert "unresolved-symbols: #" in report
    assert "`sentence-2`: 1 forced boundary" in report


@pytest.mark.parametrize(
    ("chapters", "message"),
    [
        (("missing",), "does not exist"),
        (("chapter-2", "chapter-1"), "manifest order"),
        (("chapter-1", "chapter-3"), "contiguous"),
        (("chapter-1", "chapter-1"), "duplicates"),
    ],
)
def test_run_rejects_invalid_scope_after_full_text_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chapters: tuple[str, ...],
    message: str,
) -> None:
    config_path, root, ingest, normalize, chunk = _project(tmp_path)
    calls: list[str] = []
    _patch_text_stages(monkeypatch, ingest, normalize, chunk, calls)

    with pytest.raises(RunError, match=message):
        run_book(config_path, root, chapters=chapters, text_only=True)

    assert calls == ["ingest", "normalize", "chunk"]


def test_full_run_uses_isolated_synthesis_then_verification_and_assembly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bilbo_tts import run_service

    config_path, root, ingest, normalize, chunk = _project(tmp_path)
    _patch_text_stages(monkeypatch, ingest, normalize, chunk)
    monkeypatch.setattr(
        run_service,
        "resolve_book_candidate",
        lambda *_args: SimpleNamespace(engine="fake"),
    )
    synthesis = _synthesis_summary()
    commands: list[list[str]] = []

    def command_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(synthesis.model_dump(mode="json")),
            stderr="",
        )

    verification_arguments: dict[str, object] = {}
    assembly_arguments: dict[str, object] = {}

    def verify(_config: Path, _root: Path, **kwargs: object) -> VerifySummary:
        verification_arguments.update(kwargs)
        return _verify_summary()

    def assemble(_config: Path, _root: Path, **kwargs: object) -> AssembleSummary:
        assembly_arguments.update(kwargs)
        return _assembly_summary()

    monkeypatch.setattr(run_service, "run_verification_loop", verify)
    monkeypatch.setattr(run_service, "assemble_book", assemble)
    summary = run_book(
        config_path,
        root,
        chapters=("chapter-1", "chapter-2"),
        command_runner=command_runner,
        pixi_executable=tmp_path / "pixi",
    )

    assert isinstance(summary, RunSummary)
    assert summary.schema_version == "run-summary/v1"
    assert summary.scope_chapter_ids == ("chapter-1", "chapter-2")
    assert commands[0][:7] == [
        str(tmp_path / "pixi"),
        "run",
        "-e",
        "default",
        "bilbo",
        "synthesize",
        str(config_path),
    ]
    assert commands[0][-4:] == [
        "--chapter",
        "chapter-1",
        "--chapter",
        "chapter-2",
    ]
    assert verification_arguments["chapters"] == ("chapter-1", "chapter-2")
    assert verification_arguments["command_runner"] is command_runner
    assert verification_arguments["pixi_executable"] == tmp_path / "pixi"
    assert assembly_arguments == {"chapters": ("chapter-1", "chapter-2")}
    report = (root / "work" / "book" / RUN_REPORT_PATH).read_text(encoding="utf-8")
    assert "Build-bundle packaging is intentionally deferred" in report


def test_second_full_run_reports_subprocess_and_assembly_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bilbo_tts import run_service

    config_path, root, ingest, normalize, chunk = _project(tmp_path)
    _patch_text_stages(monkeypatch, ingest, normalize, chunk)
    monkeypatch.setattr(
        run_service,
        "resolve_book_candidate",
        lambda *_args: SimpleNamespace(engine="fake"),
    )
    monkeypatch.setattr(
        run_service,
        "run_verification_loop",
        lambda *_args, **_kwargs: _verify_summary(),
    )
    assembly_results = iter((_assembly_summary(), _assembly_summary(reused=True)))
    monkeypatch.setattr(
        run_service,
        "assemble_book",
        lambda *_args, **_kwargs: next(assembly_results),
    )
    synthesis_results = iter((_synthesis_summary(), _synthesis_summary(generated=0)))

    def command_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        summary = next(synthesis_results)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(summary.model_dump(mode="json")),
            stderr="",
        )

    first = run_book(
        config_path,
        root,
        command_runner=command_runner,
        pixi_executable=tmp_path / "pixi",
    )
    second = run_book(
        config_path,
        root,
        command_runner=command_runner,
        pixi_executable=tmp_path / "pixi",
    )

    assert isinstance(first, RunSummary)
    assert isinstance(second, RunSummary)
    assert first.synthesis.generated_count == 3
    assert second.synthesis.generated_count == 0
    assert second.synthesis.skipped_count == 3
    assert second.assembly.reused is True


@pytest.mark.parametrize(
    ("synthesis_status", "returncode", "expected"),
    [
        ("completed", 7, "synthesis process failed with exit code 7"),
        ("partial", 0, "synthesis did not complete"),
    ],
)
def test_synthesis_failure_stops_before_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthesis_status: str,
    returncode: int,
    expected: str,
) -> None:
    from bilbo_tts import run_service

    config_path, root, ingest, normalize, chunk = _project(tmp_path)
    _patch_text_stages(monkeypatch, ingest, normalize, chunk)
    monkeypatch.setattr(
        run_service,
        "resolve_book_candidate",
        lambda *_args: SimpleNamespace(engine="fake"),
    )
    reached: list[str] = []
    monkeypatch.setattr(
        run_service,
        "run_verification_loop",
        lambda *_args, **_kwargs: reached.append("verify"),
    )
    monkeypatch.setattr(
        run_service,
        "assemble_book",
        lambda *_args, **_kwargs: reached.append("assemble"),
    )
    synthesis = _synthesis_summary(status=synthesis_status)

    def command_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout=json.dumps(synthesis.model_dump(mode="json")),
            stderr="engine unavailable" if returncode else "",
        )

    with pytest.raises(RunError, match=expected):
        run_book(
            config_path,
            root,
            command_runner=command_runner,
            pixi_executable=tmp_path / "pixi",
        )

    assert reached == []


def test_verification_review_stops_before_assembly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bilbo_tts import run_service

    config_path, root, ingest, normalize, chunk = _project(tmp_path)
    _patch_text_stages(monkeypatch, ingest, normalize, chunk)
    monkeypatch.setattr(
        run_service,
        "resolve_book_candidate",
        lambda *_args: SimpleNamespace(engine="fake"),
    )
    monkeypatch.setattr(
        run_service,
        "run_verification_loop",
        lambda *_args, **_kwargs: _verify_summary("review"),
    )
    reached: list[str] = []
    monkeypatch.setattr(
        run_service,
        "assemble_book",
        lambda *_args, **_kwargs: reached.append("assemble"),
    )

    def command_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(_synthesis_summary().model_dump(mode="json")),
            stderr="",
        )

    with pytest.raises(RunError, match="verification did not complete"):
        run_book(
            config_path,
            root,
            command_runner=command_runner,
            pixi_executable=tmp_path / "pixi",
        )

    assert reached == []


def test_synthesis_interruption_propagates_without_starting_later_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bilbo_tts import run_service

    config_path, root, ingest, normalize, chunk = _project(tmp_path)
    _patch_text_stages(monkeypatch, ingest, normalize, chunk)
    monkeypatch.setattr(
        run_service,
        "resolve_book_candidate",
        lambda *_args: SimpleNamespace(engine="fake"),
    )
    reached: list[str] = []
    monkeypatch.setattr(
        run_service,
        "run_verification_loop",
        lambda *_args, **_kwargs: reached.append("verify"),
    )
    monkeypatch.setattr(
        run_service,
        "assemble_book",
        lambda *_args, **_kwargs: reached.append("assemble"),
    )

    def interrupt(_command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_book(
            config_path,
            root,
            command_runner=interrupt,
            pixi_executable=tmp_path / "pixi",
        )

    assert reached == []


def test_text_only_contract_rejects_inconsistent_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, root, ingest, normalize, chunk = _project(tmp_path)
    _patch_text_stages(monkeypatch, ingest, normalize, chunk)
    summary = run_book(config_path, root, text_only=True)
    payload = summary.model_dump(mode="json")
    payload["estimated_total_duration_ms"] += 1

    with pytest.raises(ValidationError, match="estimated_total_duration_ms"):
        TextOnlySummary.model_validate(payload)
