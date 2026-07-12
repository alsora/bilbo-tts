"""Content-addressed, atomically published audiobook build bundles."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import StringConstraints, field_validator, model_validator

from bilbo_tts.assembly import AssembleSummary
from bilbo_tts.chunk_service import ChunkSummary
from bilbo_tts.config import LexiconConfig, load_book_config
from bilbo_tts.ingest import IngestSummary
from bilbo_tts.models import (
    AssemblyManifest,
    BookDocument,
    ChunkManifest,
    ContractModel,
    GenerationManifest,
    Identifier,
    NonEmptyText,
    NormalizedDocument,
    Sha256,
    VerificationManifest,
)
from bilbo_tts.normalization import NormalizeSummary
from bilbo_tts.qualification.candidates import (
    AsrCandidateConfig,
    LicenseMetadata,
    TtsCandidateConfig,
    load_asr_candidate,
    load_tts_candidate,
)
from bilbo_tts.serialization import canonical_json_bytes, canonical_sha256, sha256_bytes
from bilbo_tts.stages import StageContext
from bilbo_tts.synthesis import SynthesizeSummary
from bilbo_tts.verification import VerifySummary

if TYPE_CHECKING:
    from bilbo_tts.run_service import TextOnlySummary

GitCommit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
BundleFileRole = Literal[
    "final-audiobook",
    "environment-lock",
    "book-config",
    "tts-config",
    "asr-config",
    "builtin-lexicon",
    "lexicon",
    "cover",
    "voice-reference",
    "book-document-manifest",
    "normalized-document-manifest",
    "chunk-manifest",
    "generation-manifest",
    "verification-manifest",
    "assembly-manifest",
    "extraction-report",
    "normalization-report",
    "chunking-report",
    "text-qualification-report",
    "synthesis-report",
    "verification-report",
    "assembly-report",
]
_SINGLE_FILE_ROLES: frozenset[BundleFileRole] = frozenset(
    {
        "final-audiobook",
        "environment-lock",
        "book-config",
        "tts-config",
        "asr-config",
        "builtin-lexicon",
        "book-document-manifest",
        "normalized-document-manifest",
        "chunk-manifest",
        "generation-manifest",
        "verification-manifest",
        "assembly-manifest",
        "extraction-report",
        "normalization-report",
        "chunking-report",
        "text-qualification-report",
        "synthesis-report",
        "verification-report",
        "assembly-report",
    }
)
DirectoryReplacer = Callable[[Path, Path], None]


class BuildBundleError(ValueError):
    """A complete, trustworthy build bundle cannot be produced."""


class RepositoryState(ContractModel):
    """Exact repository identity accepted for a reproducible build."""

    head_commit: GitCommit
    tracked_worktree_clean: bool


GitMetadataProvider = Callable[[Path], RepositoryState]


class BuildModelRecord(ContractModel):
    """Pinned model, backend, code, and license provenance."""

    schema_version: Literal["build-model-record/v1"] = "build-model-record/v1"
    role: Literal["tts", "asr"]
    engine: Identifier
    backend: Identifier
    model_id: NonEmptyText
    revision: NonEmptyText
    code_revision: NonEmptyText | None = None
    model_license: LicenseMetadata | None = None
    code_license: LicenseMetadata | None = None

    @model_validator(mode="after")
    def licenses_match_model_kind(self) -> Self:
        if self.role == "asr" and self.model_license is None:
            raise ValueError("ASR build records require model_license")
        if self.role == "tts" and self.engine != "fake" and self.model_license is None:
            raise ValueError("non-fake TTS build records require model_license")
        if self.engine != "fake" and self.code_revision is not None and self.code_license is None:
            raise ValueError("non-fake model code revisions require code_license")
        if self.code_license is not None and self.code_revision is None:
            raise ValueError("code_license requires code_revision")
        return self


class BuildVoiceRecord(ContractModel):
    """Voice identity and optional exact owned reference."""

    voice_id: Identifier
    reference_sha256: Sha256 | None = None


class BuildBundleFile(ContractModel):
    """One copied bundle member, excluding the manifest itself."""

    path: NonEmptyText
    sha256: Sha256
    role: BundleFileRole

    @field_validator("path")
    @classmethod
    def path_is_normalized_relative_posix(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError("bundle file path must be normalized relative POSIX")
        return value


class BuildManifest(ContractModel):
    """Canonical provenance payload that defines a bundle's identity."""

    schema_version: Literal["build-manifest/v1"] = "build-manifest/v1"
    book_id: Identifier
    book_config_sha256: Sha256
    source_sha256: Sha256
    selected_chapter_ids: tuple[Identifier, ...]
    reproducible_command: tuple[NonEmptyText, ...]
    repository: RepositoryState
    models: tuple[BuildModelRecord, ...]
    voice: BuildVoiceRecord
    environment_lock_sha256: Sha256
    files: tuple[BuildBundleFile, ...]

    @model_validator(mode="after")
    def records_are_complete_and_ordered(self) -> Self:
        if not self.selected_chapter_ids:
            raise ValueError("selected_chapter_ids must not be empty")
        if len(self.selected_chapter_ids) != len(set(self.selected_chapter_ids)):
            raise ValueError("selected_chapter_ids must be unique")
        if not self.reproducible_command:
            raise ValueError("reproducible_command must not be empty")
        if not self.repository.tracked_worktree_clean:
            raise ValueError("build repository tracked working tree must be clean")
        if tuple(record.role for record in self.models) != ("tts", "asr"):
            raise ValueError("models must contain ordered TTS and ASR records")
        paths = tuple(record.path for record in self.files)
        if len(paths) != len(set(paths)):
            raise ValueError("bundle file paths must be unique")
        if paths != tuple(sorted(paths)):
            raise ValueError("bundle files must be ordered by path")
        roles = [record.role for record in self.files]
        missing = sorted(_SINGLE_FILE_ROLES - set(roles))
        if missing:
            raise ValueError(f"bundle is missing required file roles: {', '.join(missing)}")
        for role in _SINGLE_FILE_ROLES:
            if roles.count(role) != 1:
                raise ValueError(f"bundle requires exactly one {role} file")
        return self


class BuildBundleResult(ContractModel):
    """Published content-addressed bundle identity."""

    path: NonEmptyText
    sha256: Sha256
    reused: bool


class _BundleSource(ContractModel):
    source_path: Path
    bundle_path: NonEmptyText
    sha256: Sha256
    role: BundleFileRole


def create_build_bundle(
    context: StageContext,
    config_path: Path,
    ingest: IngestSummary,
    normalization: NormalizeSummary,
    chunking: ChunkSummary,
    qualification: TextOnlySummary,
    synthesis: SynthesizeSummary,
    verification: VerifySummary,
    assembly: AssembleSummary,
    *,
    repository_root: Path,
    git_metadata_provider: GitMetadataProvider = lambda root: inspect_repository(root),
    directory_replacer: DirectoryReplacer = os.replace,
) -> BuildBundleResult:
    """Validate current evidence and atomically publish its canonical bundle."""

    repository_root = repository_root.expanduser().resolve()
    repository = git_metadata_provider(repository_root)
    if not repository.tracked_worktree_clean:
        raise BuildBundleError("repository tracked working tree must be clean")
    resolved_config = config_path.expanduser().resolve()
    if load_book_config(resolved_config) != context.config:
        raise BuildBundleError("book configuration changed after the run context was loaded")

    store = context.workspace.artifacts
    document = store.read(ingest.document_path or "", BookDocument)
    document_ref = store.reference(ingest.document_path or "")
    normalized = store.read(normalization.normalized_path, NormalizedDocument)
    normalized_ref = store.reference(normalization.normalized_path)
    chunks = store.read(chunking.chunk_manifest_path, ChunkManifest)
    chunks_ref = store.reference(chunking.chunk_manifest_path)
    generations = store.read(synthesis.generation_manifest_path, GenerationManifest)
    generations_ref = store.reference(synthesis.generation_manifest_path)
    verifications = store.read(verification.verification_manifest_path, VerificationManifest)
    verifications_ref = store.reference(verification.verification_manifest_path)
    assembled = store.read(assembly.assembly_manifest_path, AssemblyManifest)
    assembled_ref = store.reference(assembly.assembly_manifest_path)
    selected_chapters = tuple(chapter.chapter_id for chapter in qualification.chapters)
    _validate_pipeline(
        context,
        ingest,
        normalization,
        chunking,
        qualification,
        synthesis,
        verification,
        assembly,
        document,
        document_ref.sha256,
        normalized,
        normalized_ref.sha256,
        chunks,
        chunks_ref.sha256,
        generations,
        generations_ref.sha256,
        verifications,
        verifications_ref.sha256,
        assembled,
        assembled_ref.sha256,
        selected_chapters,
    )
    if _current_source_sha256(context) != document.source_sha256:
        raise BuildBundleError("configured book source changed after ingestion")

    tts_path = _repository_input(repository_root, context.config.synthesis.model_config_path)
    asr_path = _repository_input(repository_root, context.config.verification.model_config_path)
    tts = load_tts_candidate(tts_path)
    asr = load_asr_candidate(asr_path)
    lock_path = repository_root / "pixi.lock"

    sources = [
        _source(resolved_config, "config/book.yaml", "book-config"),
        _source(tts_path, "config/tts.yaml", "tts-config"),
        _source(asr_path, "config/asr.yaml", "asr-config"),
        _source(lock_path, "environment/pixi.lock", "environment-lock"),
        _source(
            store.resolve(assembly.output_path),
            f"audiobook/{Path(assembly.output_path).name}",
            "final-audiobook",
        ),
        _source(
            store.resolve(ingest.document_path or ""),
            ingest.document_path or "",
            "book-document-manifest",
        ),
        _source(
            store.resolve(normalization.normalized_path),
            normalization.normalized_path,
            "normalized-document-manifest",
        ),
        _source(
            store.resolve(chunking.chunk_manifest_path),
            chunking.chunk_manifest_path,
            "chunk-manifest",
        ),
        _source(
            store.resolve(synthesis.generation_manifest_path),
            synthesis.generation_manifest_path,
            "generation-manifest",
        ),
        _source(
            store.resolve(verification.verification_manifest_path),
            verification.verification_manifest_path,
            "verification-manifest",
        ),
        _source(
            store.resolve(assembly.assembly_manifest_path),
            assembly.assembly_manifest_path,
            "assembly-manifest",
        ),
        _checked_source(store.root, ingest.report_path, ingest.report_sha256, "extraction-report"),
        _checked_source(
            store.root,
            normalization.report_path,
            normalization.report_sha256,
            "normalization-report",
        ),
        _checked_source(
            store.root, chunking.report_path, chunking.report_sha256, "chunking-report"
        ),
        _checked_source(
            store.root,
            qualification.report_path,
            qualification.report_sha256,
            "text-qualification-report",
        ),
        _checked_source(
            store.root, synthesis.report_path, synthesis.report_sha256, "synthesis-report"
        ),
        _checked_source(
            store.root, verification.report_path, verification.report_sha256, "verification-report"
        ),
        _checked_source(
            store.root, assembly.report_path, assembly.report_sha256, "assembly-report"
        ),
    ]
    lexicon_sources, combined_lexicon_sha256 = _lexicon_sources(context, repository_root)
    if combined_lexicon_sha256 != normalized.lexicon_sha256:
        raise BuildBundleError(
            "current built-in and configured lexicons do not match the normalized document"
        )
    sources.extend(lexicon_sources)
    if context.config.metadata.cover_path is not None:
        sources.append(
            _source(
                context.book_dir.joinpath(*Path(context.config.metadata.cover_path).parts),
                f"inputs/cover/{context.config.metadata.cover_path}",
                "cover",
            )
        )
    reference_sha256 = tts.voice.reference_sha256
    if tts.voice.reference_path is not None:
        reference = _checked_source(
            context.book_dir,
            tts.voice.reference_path,
            reference_sha256 or "",
            "voice-reference",
            bundle_path=f"inputs/voice/{tts.voice.reference_path}",
        )
        sources.append(reference)

    ordered_sources = tuple(sorted(sources, key=lambda item: item.bundle_path))
    files = tuple(
        BuildBundleFile(path=item.bundle_path, sha256=item.sha256, role=item.role)
        for item in ordered_sources
    )
    manifest = BuildManifest(
        book_id=context.config.book_id,
        book_config_sha256=sha256_bytes(resolved_config.read_bytes()),
        source_sha256=document.source_sha256,
        selected_chapter_ids=selected_chapters,
        reproducible_command=_reproducible_command(
            resolved_config,
            context.workspace.project_root,
            repository_root,
            selected_chapters,
        ),
        repository=repository,
        models=(_tts_record(tts), _asr_record(asr)),
        voice=BuildVoiceRecord(
            voice_id=tts.voice.voice_id,
            reference_sha256=reference_sha256,
        ),
        environment_lock_sha256=_file_sha256(lock_path),
        files=files,
    )
    bundle_sha256 = canonical_sha256(manifest)
    relative_path = f"deliverables/build-{bundle_sha256}"
    target = store.resolve(relative_path)
    manifest_bytes = canonical_json_bytes(manifest) + b"\n"
    if target.exists():
        _validate_existing_bundle(target, manifest, manifest_bytes)
        return BuildBundleResult(path=relative_path, sha256=bundle_sha256, reused=True)
    _publish_bundle(
        target,
        ordered_sources,
        manifest,
        manifest_bytes,
        directory_replacer,
    )
    return BuildBundleResult(path=relative_path, sha256=bundle_sha256, reused=False)


def inspect_repository(repository_root: Path) -> RepositoryState:
    """Read HEAD and require a clean tracked working tree."""

    root = repository_root.expanduser().resolve()
    top = _git(root, "rev-parse", "--show-toplevel")
    try:
        actual_root = Path(top).resolve(strict=True)
    except OSError as error:
        raise BuildBundleError(f"cannot resolve Git repository root {top!r}: {error}") from error
    if actual_root != root:
        raise BuildBundleError(
            f"repository root mismatch: expected {root}, Git reports {actual_root}"
        )
    head = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise BuildBundleError("repository tracked working tree must be clean")
    try:
        return RepositoryState(head_commit=head, tracked_worktree_clean=True)
    except ValueError as error:
        raise BuildBundleError(f"Git reported an invalid HEAD commit: {head!r}") from error


def _validate_pipeline(
    context: StageContext,
    ingest: IngestSummary,
    normalization: NormalizeSummary,
    chunking: ChunkSummary,
    qualification: TextOnlySummary,
    synthesis: SynthesizeSummary,
    verification: VerifySummary,
    assembly: AssembleSummary,
    document: BookDocument,
    document_sha256: str,
    normalized: NormalizedDocument,
    normalized_sha256: str,
    chunks: ChunkManifest,
    chunks_sha256: str,
    generations: GenerationManifest,
    generations_sha256: str,
    verifications: VerificationManifest,
    verifications_sha256: str,
    assembled: AssemblyManifest,
    assembled_sha256: str,
    selected_chapters: tuple[str, ...],
) -> None:
    book_ids = {
        context.config.book_id,
        ingest.book_id,
        normalization.book_id,
        chunking.book_id,
        qualification.book_id,
        synthesis.book_id,
        verification.book_id,
        assembly.book_id,
        document.book_id,
        normalized.book_id,
        chunks.book_id,
        generations.book_id,
        verifications.book_id,
        assembled.book_id,
    }
    if len(book_ids) != 1:
        raise BuildBundleError("bundle inputs do not belong to one configured book")
    if ingest.status != "completed" or ingest.source_sha256 != document.source_sha256:
        raise BuildBundleError("ingestion summary does not reference the current source")
    expected_links = (
        (ingest.document_sha256, document_sha256, "ingestion document"),
        (normalization.document_sha256, document_sha256, "normalization document"),
        (normalized.book_document_sha256, document_sha256, "normalized document"),
        (normalization.normalized_sha256, normalized_sha256, "normalization output"),
        (chunking.normalized_sha256, normalized_sha256, "chunking input"),
        (chunks.normalized_document_sha256, normalized_sha256, "chunk manifest"),
        (chunking.chunk_manifest_sha256, chunks_sha256, "chunking output"),
        (qualification.document_sha256, document_sha256, "text qualification document"),
        (qualification.normalized_sha256, normalized_sha256, "text qualification normalization"),
        (qualification.chunk_manifest_sha256, chunks_sha256, "text qualification chunks"),
        (synthesis.chunk_manifest_sha256, chunks_sha256, "synthesis chunks"),
        (generations.chunk_manifest_sha256, chunks_sha256, "generation manifest"),
        (synthesis.generation_manifest_sha256, generations_sha256, "synthesis output"),
        (verifications.generation_manifest_sha256, generations_sha256, "verification generations"),
        (verification.verification_manifest_sha256, verifications_sha256, "verification output"),
        (assembled.book_document_sha256, document_sha256, "assembly document"),
        (assembled.chunk_manifest_sha256, chunks_sha256, "assembly chunks"),
        (assembled.generation_manifest_sha256, generations_sha256, "assembly generations"),
        (assembled.verification_manifest_sha256, verifications_sha256, "assembly verification"),
        (assembly.assembly_manifest_sha256, assembled_sha256, "assembly output"),
    )
    for actual, expected, label in expected_links:
        if actual != expected:
            raise BuildBundleError(f"{label} is stale or references the wrong upstream artifact")
    if assembled.scope_chapter_ids != selected_chapters:
        raise BuildBundleError("assembly scope does not match the ordered run scope")
    if (
        assembled.output_path != assembly.output_path
        or assembled.output_sha256 != assembly.output_sha256
    ):
        raise BuildBundleError("assembly summary does not reference the current final media")
    if (
        _file_sha256(context.workspace.artifacts.resolve(assembly.output_path))
        != assembly.output_sha256
    ):
        raise BuildBundleError("final media checksum does not match the assembly")


def _tts_record(candidate: TtsCandidateConfig) -> BuildModelRecord:
    return BuildModelRecord(
        role="tts",
        engine=candidate.engine,
        backend=candidate.backend,
        model_id=candidate.model_id,
        revision=candidate.model.revision,
        code_revision=candidate.code_revision,
        model_license=candidate.model_license,
        code_license=candidate.code_license,
    )


def _asr_record(candidate: AsrCandidateConfig) -> BuildModelRecord:
    return BuildModelRecord(
        role="asr",
        engine=candidate.engine,
        backend=candidate.backend,
        model_id=candidate.model_id,
        revision=candidate.revision,
        model_license=candidate.model_license,
    )


def _current_source_sha256(context: StageContext) -> str:
    source = context.book_dir.joinpath(*Path(context.config.input.path).parts)
    if context.config.input.format.value == "pdf":
        return _file_sha256(source)
    source_root = source.parent
    files: list[dict[str, str]] = []
    try:
        paths = sorted(source_root.rglob("*"))
    except OSError as error:
        raise BuildBundleError(f"cannot inspect configured LaTeX source tree: {error}") from error
    for path in paths:
        if path.is_symlink():
            raise BuildBundleError(f"configured LaTeX source tree contains a symlink: {path}")
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(source_root).as_posix(),
                    "sha256": _file_sha256(path),
                }
            )
    if not files:
        raise BuildBundleError(f"configured LaTeX source tree contains no files: {source_root}")
    return canonical_sha256({"entry_point": source.name, "files": files})


def _lexicon_sources(
    context: StageContext,
    repository_root: Path,
) -> tuple[list[_BundleSource], str]:
    builtin = _source(
        repository_root / "config" / "lexicons" / "finance-it.yaml",
        "config/lexicons/000-builtin-finance-it.yaml",
        "builtin-lexicon",
    )
    sources = [builtin]
    identities = [{"source": "builtin:finance-it", "sha256": builtin.sha256}]
    for index, item in enumerate(context.config.normalization.lexicons):
        root = context.book_dir if item.scope == "book" else repository_root / "config" / "lexicons"
        source = root.joinpath(*Path(item.path).parts)
        checked = _checked_lexicon_source(
            source,
            item,
            f"config/lexicons/{index + 1:03d}-{item.scope}-{Path(item.path).name}",
        )
        sources.append(checked)
        identities.append(
            {
                "source": f"{item.scope}:{item.path}",
                "sha256": checked.sha256,
            }
        )
    return sources, canonical_sha256(identities)


def _checked_lexicon_source(
    path: Path,
    configured: LexiconConfig,
    bundle_path: str,
) -> _BundleSource:
    source = _source(path, bundle_path, "lexicon")
    if source.sha256 != configured.sha256:
        raise BuildBundleError(
            f"configured {configured.scope} lexicon checksum does not match: {configured.path}"
        )
    return source


def _repository_input(repository_root: Path, relative_path: str) -> Path:
    path = repository_root.joinpath(*Path(relative_path).parts).resolve(strict=False)
    if not path.is_relative_to(repository_root):
        raise BuildBundleError(f"repository input escapes repository root: {relative_path}")
    return path


def _source(path: Path, bundle_path: str, role: BundleFileRole) -> _BundleSource:
    normalized = PurePosixPath(bundle_path)
    if normalized.is_absolute() or ".." in normalized.parts or normalized.as_posix() != bundle_path:
        raise BuildBundleError(f"invalid bundle destination path: {bundle_path}")
    return _BundleSource(
        source_path=path,
        bundle_path=bundle_path,
        sha256=_file_sha256(path),
        role=role,
    )


def _checked_source(
    root: Path,
    relative_path: str,
    expected_sha256: str,
    role: BundleFileRole,
    *,
    bundle_path: str | None = None,
) -> _BundleSource:
    source = _source(
        root.joinpath(*Path(relative_path).parts),
        bundle_path or relative_path,
        role,
    )
    if source.sha256 != expected_sha256:
        raise BuildBundleError(
            f"{role} checksum does not match its current summary: {relative_path}"
        )
    return source


def _reproducible_command(
    config_path: Path,
    project_root: Path,
    repository_root: Path,
    selected_chapters: Sequence[str],
) -> tuple[str, ...]:
    command = [
        ".tools/bin/pixi",
        "run",
        "bilbo",
        "run",
        _relative_argument(config_path, repository_root),
        "--project-root",
        _relative_argument(project_root, repository_root),
    ]
    for chapter_id in selected_chapters:
        command.extend(("--chapter", chapter_id))
    return tuple(command)


def _relative_argument(path: Path, repository_root: Path) -> str:
    relative = os.path.relpath(path.resolve(), repository_root)
    return Path(relative).as_posix()


def _publish_bundle(
    target: Path,
    sources: Sequence[_BundleSource],
    manifest: BuildManifest,
    manifest_bytes: bytes,
    replacer: DirectoryReplacer,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".build-bundle-", dir=target.parent))
    published = False
    try:
        for source in sources:
            destination = staging.joinpath(*PurePosixPath(source.bundle_path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(source.source_path, destination)
            except OSError as error:
                raise BuildBundleError(
                    f"cannot copy {source.source_path} into build bundle: {error}"
                ) from error
            if _file_sha256(destination) != source.sha256:
                raise BuildBundleError(f"bundle source changed while copying: {source.source_path}")
        manifest_path = staging / "build-manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        try:
            replacer(staging, target)
        except OSError as error:
            raise BuildBundleError(
                f"cannot atomically publish build bundle {target}: {error}"
            ) from error
        published = True
        _fsync_directory(target.parent)
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)
    _validate_existing_bundle(target, manifest, manifest_bytes)


def _validate_existing_bundle(
    target: Path,
    manifest: BuildManifest,
    manifest_bytes: bytes,
) -> None:
    expected = {record.path for record in manifest.files} | {"build-manifest.json"}
    actual: set[str] = set()
    try:
        for path in target.rglob("*"):
            if path.is_symlink():
                raise BuildBundleError(f"build bundle contains a symlink: {path}")
            if path.is_file():
                actual.add(path.relative_to(target).as_posix())
    except OSError as error:
        raise BuildBundleError(f"cannot inspect existing build bundle {target}: {error}") from error
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise BuildBundleError(
            f"existing build bundle file set differs; missing={missing}, unexpected={unexpected}"
        )
    if (target / "build-manifest.json").read_bytes() != manifest_bytes:
        raise BuildBundleError("existing build bundle manifest is stale or tampered")
    for record in manifest.files:
        path = target.joinpath(*PurePosixPath(record.path).parts)
        if _file_sha256(path) != record.sha256:
            raise BuildBundleError(f"existing build bundle file is tampered: {record.path}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    except OSError as error:
        raise BuildBundleError(f"cannot read required bundle input {path}: {error}") from error
    return digest.hexdigest()


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise BuildBundleError(f"cannot inspect Git repository: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise BuildBundleError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout.strip()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise BuildBundleError(
            f"cannot synchronize build bundle directory {path}: {error}"
        ) from error
