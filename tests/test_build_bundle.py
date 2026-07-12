from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from bilbo_tts.assembly import AssembleSummary
from bilbo_tts.build_bundle import (
    BuildBundleError,
    BuildBundleResult,
    BuildManifest,
    DirectoryReplacer,
    RepositoryState,
    create_build_bundle,
)
from bilbo_tts.chunk_service import ChunkSummary
from bilbo_tts.ingest import IngestSummary
from bilbo_tts.models import (
    AssemblyInputRecord,
    AssemblyManifest,
    BlockKind,
    BookDocument,
    BreakKind,
    ChapterDocument,
    ChapterMarker,
    ChunkManifest,
    ChunkRecord,
    DocumentBlock,
    GenerationManifest,
    NormalizedBlock,
    NormalizedDocument,
    PauseMetadata,
    ProbedMedia,
    SourceFormat,
    SourceLocation,
    VerificationManifest,
)
from bilbo_tts.normalization import NormalizeSummary
from bilbo_tts.run_service import (
    RunSummary,
    TextOnlyChapterSummary,
    TextOnlySummary,
    run_book,
)
from bilbo_tts.serialization import canonical_sha256, sha256_bytes
from bilbo_tts.stages import StageContext, load_stage_context
from bilbo_tts.synthesis import SynthesizeSummary
from bilbo_tts.verification import VerifySummary

COMMIT = "1" * 40
HASH = "a" * 64


@dataclass(frozen=True)
class BundleFixture:
    repository_root: Path
    context: StageContext
    config_path: Path
    ingest: IngestSummary
    normalization: NormalizeSummary
    chunking: ChunkSummary
    qualification: TextOnlySummary
    synthesis: SynthesizeSummary
    verification: VerifySummary
    assembly: AssembleSummary


def _fixture(tmp_path: Path) -> BundleFixture:
    repository_root = tmp_path / "repository"
    project_root = tmp_path / "project"
    book_dir = project_root / "books" / "book"
    repository_root.joinpath("config/qualification").mkdir(parents=True)
    repository_root.joinpath("config/lexicons").mkdir(parents=True)
    book_dir.joinpath("source").mkdir(parents=True)

    source = book_dir / "source" / "book.tex"
    source.write_text("Testo.", encoding="utf-8")
    cover = book_dir / "cover.png"
    cover.write_bytes(b"cover")
    (project_root / "voice.wav").write_bytes(b"wrong reference base")
    reference = book_dir / "voice.wav"
    reference.write_bytes(b"reference")
    builtin_lexicon = repository_root / "config" / "lexicons" / "finance-it.yaml"
    builtin_lexicon.write_bytes(b"built-in lexicon\n")
    book_lexicon = book_dir / "book-lex.yaml"
    book_lexicon.write_bytes(b"book lexicon\n")
    shared_lexicon = repository_root / "config" / "lexicons" / "shared.yaml"
    shared_lexicon.write_bytes(b"shared lexicon\n")

    tts_path = repository_root / "config" / "qualification" / "fake.yaml"
    tts_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "tts-candidate/v1",
                "engine": "fake",
                "backend": "stdlib",
                "model_id": "bilbo-tts/fake",
                "model": {"engine": "fake", "revision": "fake-v1"},
                "voice": {
                    "voice_id": "fake-voice",
                    "reference_path": "voice.wav",
                    "reference_sha256": sha256_bytes(reference.read_bytes()),
                },
                "settings": {"sample_rate_hz": 24_000, "seed": 1},
                "inference_parameters": {},
            }
        ),
        encoding="utf-8",
    )
    asr_path = repository_root / "config" / "qualification" / "asr.yaml"
    asr_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "asr-candidate/v1",
                "engine": "mlx-whisper",
                "backend": "mlx",
                "model_id": "mlx-community/whisper-large-v3-turbo",
                "revision": "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb",
                "model_license": {
                    "spdx_identifier": "MIT",
                    "source_url": "https://github.com/openai/whisper/blob/main/LICENSE",
                },
                "language": "it",
            }
        ),
        encoding="utf-8",
    )
    (repository_root / "pixi.lock").write_bytes(b"locked environment\n")
    config_path = book_dir / "book.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "book-config/v1",
                "book_id": "book",
                "language": "it",
                "input": {"format": "latex", "path": "source/book.tex"},
                "metadata": {
                    "title": "Libro",
                    "author": "Autrice",
                    "cover_path": "cover.png",
                },
                "normalization": {
                    "version": "it-v1",
                    "lexicons": [
                        {
                            "path": "book-lex.yaml",
                            "sha256": sha256_bytes(book_lexicon.read_bytes()),
                            "scope": "book",
                        },
                        {
                            "path": "shared.yaml",
                            "sha256": sha256_bytes(shared_lexicon.read_bytes()),
                            "scope": "shared",
                        },
                    ],
                },
                "chunking": {"max_characters": 100},
                "synthesis": {"model_config_path": "config/qualification/fake.yaml"},
                "verification": {"model_config_path": "config/qualification/asr.yaml"},
                "assembly": {},
            }
        ),
        encoding="utf-8",
    )
    context = load_stage_context(config_path, project_root)
    store = context.workspace.artifacts

    document = BookDocument(
        book_id="book",
        source_format=SourceFormat.LATEX,
        source_sha256=canonical_sha256(
            {
                "entry_point": source.name,
                "files": [
                    {
                        "path": source.name,
                        "sha256": sha256_bytes(source.read_bytes()),
                    }
                ],
            }
        ),
        chapters=(
            ChapterDocument(
                chapter_id="chapter-1",
                order=0,
                title="Capitolo",
                blocks=(
                    DocumentBlock(
                        block_id="block-1",
                        kind=BlockKind.PARAGRAPH,
                        display_text="Testo.",
                        source=SourceLocation(source_path="source/book.tex"),
                    ),
                ),
            ),
        ),
    )
    document_ref = store.write("manifests/book-document.json", document)
    combined_lexicon_sha256 = canonical_sha256(
        [
            {
                "source": "builtin:finance-it",
                "sha256": sha256_bytes(builtin_lexicon.read_bytes()),
            },
            {
                "source": "book:book-lex.yaml",
                "sha256": sha256_bytes(book_lexicon.read_bytes()),
            },
            {
                "source": "shared:shared.yaml",
                "sha256": sha256_bytes(shared_lexicon.read_bytes()),
            },
        ]
    )
    normalized = NormalizedDocument(
        book_id="book",
        book_document_sha256=document_ref.sha256,
        normalization_version="it-v1",
        lexicon_sha256=combined_lexicon_sha256,
        blocks=(
            NormalizedBlock(
                block_id="block-1",
                display_text="Testo.",
                spoken_text="Testo.",
            ),
        ),
    )
    normalized_ref = store.write(
        "manifests/normalized-document.json",
        normalized,
        dependencies=(document_ref,),
    )
    chunk = ChunkRecord.create(
        chunk_id="chunk-1",
        chapter_id="chapter-1",
        paragraph_id="block-1",
        sentence_id="sentence-1",
        sequence=0,
        display_text="Testo.",
        spoken_text="Testo.",
        pause=PauseMetadata(break_before=BreakKind.CHAPTER, duration_ms=100),
    )
    chunks = ChunkManifest(
        book_id="book",
        normalized_document_sha256=normalized_ref.sha256,
        chunks=(chunk,),
    )
    chunks_ref = store.write(
        "manifests/chunk-manifest.json",
        chunks,
        dependencies=(document_ref, normalized_ref),
    )
    generations = GenerationManifest(
        book_id="book",
        chunk_manifest_sha256=chunks_ref.sha256,
        records=(),
    )
    generations_ref = store.write(
        "manifests/generation-manifest.json",
        generations,
        dependencies=(chunks_ref,),
    )
    verifications = VerificationManifest(
        book_id="book",
        generation_manifest_sha256=generations_ref.sha256,
        verification_config_sha256=HASH,
        asr_model_id="mlx-community/whisper-large-v3-turbo",
        asr_model_revision="a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb",
        records=(),
    )
    verifications_ref = store.write(
        "manifests/verification-manifest.json",
        verifications,
        dependencies=(generations_ref,),
    )
    output_path = "media/book.m4b"
    output_ref = store.write_bytes(output_path, b"m4b")
    assembled = AssemblyManifest(
        book_id="book",
        scope_chapter_ids=("chapter-1",),
        book_document_sha256=document_ref.sha256,
        chunk_manifest_sha256=chunks_ref.sha256,
        generation_manifest_sha256=generations_ref.sha256,
        verification_manifest_sha256=verifications_ref.sha256,
        assembly_input_sha256=HASH,
        sample_rate_hz=24_000,
        total_frame_count=100,
        inputs=(
            AssemblyInputRecord(
                chunk_id="chunk-1",
                sequence=0,
                generation_sha256=HASH,
                output_path="audio/chunk-1.wav",
                output_sha256=HASH,
                audio_frame_count=100,
                pause_frame_count=0,
                start_frame=0,
            ),
        ),
        chapters=(
            ChapterMarker(
                chapter_id="chapter-1",
                title="Capitolo",
                start_frame=0,
                end_frame=100,
            ),
        ),
        commands=(),
        loudness=(),
        output_path=output_path,
        output_sha256=output_ref.sha256,
        media=ProbedMedia(
            codec_name="aac",
            channels=1,
            sample_rate_hz=24_000,
            duration_ms=4,
            tags={"title": "Libro", "artist": "Autrice"},
            cover_art=True,
            chapter_count=1,
        ),
    )
    assembled_ref = store.write(
        "manifests/assembly-manifest.json",
        assembled,
        dependencies=(document_ref, chunks_ref, generations_ref, verifications_ref),
    )

    reports = {
        name: store.write_bytes(f"reports/{name}.md", f"{name}\n".encode())
        for name in (
            "extraction",
            "normalization",
            "chunking",
            "text-only-qualification",
            "synthesis",
            "verification",
            "assembly",
        )
    }
    ingest = IngestSummary(
        status="completed",
        book_id="book",
        source_format=SourceFormat.LATEX,
        source_sha256=document.source_sha256,
        document_path=document_ref.path,
        document_sha256=document_ref.sha256,
        report_path=reports["extraction"].path,
        report_sha256=reports["extraction"].sha256,
        chapter_count=1,
        block_count=1,
    )
    normalization = NormalizeSummary(
        book_id="book",
        document_sha256=document_ref.sha256,
        normalized_path=normalized_ref.path,
        normalized_sha256=normalized_ref.sha256,
        report_path=reports["normalization"].path,
        report_sha256=reports["normalization"].sha256,
        block_count=1,
        transformation_count=0,
        lexicon_application_count=0,
        warning_count=0,
    )
    chunking = ChunkSummary(
        book_id="book",
        normalized_sha256=normalized_ref.sha256,
        chunk_manifest_path=chunks_ref.path,
        chunk_manifest_sha256=chunks_ref.sha256,
        report_path=reports["chunking"].path,
        report_sha256=reports["chunking"].sha256,
        chunk_count=1,
        max_characters=100,
        largest_chunk_characters=6,
    )
    chapter = TextOnlyChapterSummary(
        chapter_id="chapter-1",
        title="Capitolo",
        block_count=1,
        word_count=1,
        chunk_count=1,
        extraction_warning_count=0,
        normalization_warning_count=0,
        unresolved_token_count=0,
        chunk_outlier_count=1,
        chunk_outlier_ids=("chunk-1",),
        forced_split_count=0,
        estimated_speech_duration_ms=400,
        configured_pause_duration_ms=100,
        estimated_total_duration_ms=500,
    )
    qualification = TextOnlySummary(
        book_id="book",
        chapters=(chapter,),
        chapter_count=1,
        block_count=1,
        word_count=1,
        chunk_count=1,
        exclusion_count=0,
        extraction_warning_count=0,
        normalization_warning_count=0,
        unresolved_token_count=0,
        chunk_outlier_count=1,
        chunk_outlier_ids=("chunk-1",),
        forced_split_count=0,
        estimated_speech_duration_ms=400,
        configured_pause_duration_ms=100,
        estimated_total_duration_ms=500,
        document_sha256=document_ref.sha256,
        normalized_sha256=normalized_ref.sha256,
        chunk_manifest_sha256=chunks_ref.sha256,
        report_path=reports["text-only-qualification"].path,
        report_sha256=reports["text-only-qualification"].sha256,
    )
    synthesis = SynthesizeSummary(
        status="completed",
        book_id="book",
        chunk_manifest_sha256=chunks_ref.sha256,
        selected_count=1,
        generated_count=1,
        skipped_count=0,
        failed_count=0,
        missing_count=0,
        generation_manifest_path=generations_ref.path,
        generation_manifest_sha256=generations_ref.sha256,
        report_path=reports["synthesis"].path,
        report_sha256=reports["synthesis"].sha256,
    )
    verification = VerifySummary(
        status="completed",
        book_id="book",
        selected_count=1,
        transcribed_count=1,
        reused_count=0,
        accepted_count=1,
        retryable_count=0,
        review_count=0,
        verification_manifest_path=verifications_ref.path,
        verification_manifest_sha256=verifications_ref.sha256,
        report_path=reports["verification"].path,
        report_sha256=reports["verification"].sha256,
    )
    assembly = AssembleSummary(
        status="completed",
        book_id="book",
        selected_count=1,
        reused=False,
        output_path=output_path,
        output_sha256=output_ref.sha256,
        assembly_manifest_path=assembled_ref.path,
        assembly_manifest_sha256=assembled_ref.sha256,
        report_path=reports["assembly"].path,
        report_sha256=reports["assembly"].sha256,
    )
    return BundleFixture(
        repository_root=repository_root,
        context=context,
        config_path=config_path,
        ingest=ingest,
        normalization=normalization,
        chunking=chunking,
        qualification=qualification,
        synthesis=synthesis,
        verification=verification,
        assembly=assembly,
    )


def _create(
    fixture: BundleFixture,
    *,
    clean: bool = True,
    replacer: DirectoryReplacer = os.replace,
) -> BuildBundleResult:
    return create_build_bundle(
        fixture.context,
        fixture.config_path,
        fixture.ingest,
        fixture.normalization,
        fixture.chunking,
        fixture.qualification,
        fixture.synthesis,
        fixture.verification,
        fixture.assembly,
        repository_root=fixture.repository_root,
        git_metadata_provider=lambda _root: RepositoryState(
            head_commit=COMMIT,
            tracked_worktree_clean=clean,
        ),
        directory_replacer=replacer,
    )


def test_bundle_contains_canonical_provenance_and_all_checksummed_inputs(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    result = _create(fixture)
    bundle = fixture.context.workspace.artifacts.resolve(result.path)
    manifest_bytes = (bundle / "build-manifest.json").read_bytes()
    manifest = BuildManifest.model_validate_json(manifest_bytes)

    assert result.path == f"deliverables/build-{result.sha256}"
    assert result.sha256 == canonical_sha256(manifest)
    assert result.reused is False
    assert manifest.book_config_sha256 == sha256_bytes(fixture.config_path.read_bytes())
    assert manifest.source_sha256 == fixture.ingest.source_sha256
    assert manifest.selected_chapter_ids == ("chapter-1",)
    assert manifest.reproducible_command == (
        ".tools/bin/pixi",
        "run",
        "bilbo",
        "run",
        "../project/books/book/book.yaml",
        "--project-root",
        "../project",
        "--chapter",
        "chapter-1",
    )
    assert manifest.repository.head_commit == COMMIT
    assert manifest.models[0].model_id == "bilbo-tts/fake"
    assert manifest.models[1].model_license is not None
    assert manifest.models[1].model_license.spdx_identifier == "MIT"
    assert manifest.voice.reference_sha256 == sha256_bytes(b"reference")
    assert (bundle / "inputs" / "voice" / "voice.wav").read_bytes() == b"reference"
    roles = [record.role for record in manifest.files]
    assert roles.count("lexicon") == 2
    assert {"builtin-lexicon", "cover", "voice-reference"} <= set(roles)
    assert "run-report" not in roles
    assert [
        record.path for record in manifest.files if record.role in {"builtin-lexicon", "lexicon"}
    ] == [
        "config/lexicons/000-builtin-finance-it.yaml",
        "config/lexicons/001-book-book-lex.yaml",
        "config/lexicons/002-shared-shared.yaml",
    ]
    assert "build-manifest.json" not in {record.path for record in manifest.files}
    for record in manifest.files:
        assert sha256_bytes((bundle / record.path).read_bytes()) == record.sha256


def test_bundle_rerun_reuses_identical_directory_byte_for_byte(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first = _create(fixture)
    bundle = fixture.context.workspace.artifacts.resolve(first.path)
    before = {
        path.relative_to(bundle).as_posix(): path.read_bytes()
        for path in bundle.rglob("*")
        if path.is_file()
    }

    second = _create(fixture)

    assert second.model_copy(update={"reused": False}) == first
    assert second.reused is True
    assert before == {
        path.relative_to(bundle).as_posix(): path.read_bytes()
        for path in bundle.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("tamper", ("change", "missing", "extra"))
def test_existing_bundle_tampering_fails_instead_of_silent_reuse(
    tmp_path: Path,
    tamper: str,
) -> None:
    fixture = _fixture(tmp_path)
    result = _create(fixture)
    bundle = fixture.context.workspace.artifacts.resolve(result.path)
    if tamper == "change":
        (bundle / "config" / "book.yaml").write_bytes(b"tampered")
    elif tamper == "missing":
        (bundle / "config" / "book.yaml").unlink()
    else:
        (bundle / "unexpected").write_bytes(b"extra")

    with pytest.raises(BuildBundleError, match="tampered|file set differs"):
        _create(fixture)


def test_atomic_publication_failure_leaves_no_partial_bundle(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("injected publication failure")

    with pytest.raises(BuildBundleError, match="atomically publish"):
        _create(fixture, replacer=fail_replace)

    deliverables = fixture.context.workspace.artifacts.resolve("deliverables")
    assert list(deliverables.iterdir()) == []


def test_dirty_tracked_repository_is_rejected_before_publication(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises(BuildBundleError, match="tracked working tree must be clean"):
        _create(fixture, clean=False)

    assert not fixture.context.workspace.artifacts.resolve("deliverables").exists()


def test_source_changed_after_ingestion_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.config_path.parent.joinpath("source/book.tex").write_text(
        "changed",
        encoding="utf-8",
    )

    with pytest.raises(BuildBundleError, match="source changed after ingestion"):
        _create(fixture)


def test_builtin_lexicon_tamper_is_rejected_against_normalized_identity(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.repository_root.joinpath("config/lexicons/finance-it.yaml").write_bytes(
        b"tampered built-in\n"
    )

    with pytest.raises(BuildBundleError, match="lexicons do not match"):
        _create(fixture)


def test_build_manifest_rejects_omitted_builtin_lexicon(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = _create(fixture)
    manifest_path = fixture.context.workspace.artifacts.resolve(result.path) / "build-manifest.json"
    payload = json.loads(manifest_path.read_bytes())
    payload["files"] = [
        record for record in payload["files"] if record["role"] != "builtin-lexicon"
    ]

    with pytest.raises(ValidationError, match="missing required file roles: builtin-lexicon"):
        BuildManifest.model_validate(payload)


def test_build_manifest_rejects_duplicate_file_paths(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = _create(fixture)
    manifest_path = fixture.context.workspace.artifacts.resolve(result.path) / "build-manifest.json"
    payload = json.loads(manifest_path.read_bytes())
    payload["files"].append(payload["files"][0])

    with pytest.raises(ValidationError, match="unique"):
        BuildManifest.model_validate(payload)


def test_full_fake_orchestration_reuses_the_same_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bilbo_tts import run_service

    fixture = _fixture(tmp_path)
    monkeypatch.setattr(run_service, "REPOSITORY_ROOT", fixture.repository_root)
    monkeypatch.setattr(run_service, "ingest_book", lambda *_args: fixture.ingest)
    monkeypatch.setattr(run_service, "normalize_book", lambda *_args: fixture.normalization)
    monkeypatch.setattr(run_service, "chunk_book", lambda *_args: fixture.chunking)
    monkeypatch.setattr(
        run_service,
        "resolve_book_candidate",
        lambda *_args: SimpleNamespace(engine="fake"),
    )
    monkeypatch.setattr(
        run_service,
        "run_verification_loop",
        lambda *_args, **_kwargs: fixture.verification,
    )
    assemblies = iter(
        (
            fixture.assembly,
            fixture.assembly.model_copy(update={"reused": True}),
        )
    )
    monkeypatch.setattr(
        run_service,
        "assemble_book",
        lambda *_args, **_kwargs: next(assemblies),
    )
    syntheses = iter(
        (
            fixture.synthesis,
            fixture.synthesis.model_copy(
                update={
                    "generated_count": 0,
                    "skipped_count": 1,
                }
            ),
        )
    )

    def command_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        synthesis = next(syntheses)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(synthesis.model_dump(mode="json")),
            stderr="",
        )

    def git_metadata(_root: Path) -> RepositoryState:
        return RepositoryState(
            head_commit=COMMIT,
            tracked_worktree_clean=True,
        )

    first = run_book(
        fixture.config_path,
        fixture.context.workspace.project_root,
        command_runner=command_runner,
        pixi_executable=tmp_path / "pixi",
        git_metadata_provider=git_metadata,
    )
    second = run_book(
        fixture.config_path,
        fixture.context.workspace.project_root,
        command_runner=command_runner,
        pixi_executable=tmp_path / "pixi",
        git_metadata_provider=git_metadata,
    )

    assert isinstance(first, RunSummary)
    assert isinstance(second, RunSummary)
    assert first.bundle_sha256 == second.bundle_sha256
    assert first.bundle_path == second.bundle_path
    assert first.bundle_reused is False
    assert second.bundle_reused is True
    assert (first.synthesis.generated_count, first.synthesis.skipped_count) == (1, 0)
    assert (second.synthesis.generated_count, second.synthesis.skipped_count) == (0, 1)
    assert first.assembly.reused is False
    assert second.assembly.reused is True
    report = fixture.context.workspace.artifacts.resolve(second.report_path).read_text(
        encoding="utf-8"
    )
    assert "0 generated; 1 reused" in report
    assert "Assembly reused: yes" in report
    assert f"Build bundle: `{second.bundle_path}`" in report
