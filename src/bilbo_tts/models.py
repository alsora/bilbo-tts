"""Versioned, validated contracts shared by pipeline stages."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from bilbo_tts.serialization import canonical_sha256

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ContractModel(BaseModel):
    """Strict immutable base for persistent contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceFormat(StrEnum):
    """Supported source document formats."""

    LATEX = "latex"
    PDF = "pdf"


class BlockKind(StrEnum):
    """Structural roles preserved by source ingestion."""

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    QUOTATION = "quotation"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    TABLE = "table"
    EQUATION = "equation"


class BreakKind(StrEnum):
    """Pause inserted before a synthesized chunk."""

    NONE = "none"
    SENTENCE = "sentence"
    PARAGRAPH = "paragraph"
    CHAPTER = "chapter"


class ReviewStatus(StrEnum):
    """Verification disposition for generated audio."""

    ACCEPTED = "accepted"
    RETRYABLE = "retryable"
    REVIEW = "review"


class SourceLocation(ContractModel):
    """Trace a document block back to its source."""

    source_path: NonEmptyText
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("start_line and end_line must be provided together")
        if (
            self.start_line is not None
            and self.end_line is not None
            and self.end_line < self.start_line
        ):
            raise ValueError("end_line must not precede start_line")
        return self


class DocumentBlock(ContractModel):
    """One ordered unit of untouched source text."""

    block_id: Identifier
    kind: BlockKind
    display_text: NonEmptyText
    source: SourceLocation
    warnings: tuple[NonEmptyText, ...] = ()


class ChapterDocument(ContractModel):
    """An ordered source chapter."""

    chapter_id: Identifier
    order: int = Field(ge=0)
    title: NonEmptyText
    blocks: tuple[DocumentBlock, ...]

    @field_validator("blocks")
    @classmethod
    def blocks_are_unique(cls, blocks: tuple[DocumentBlock, ...]) -> tuple[DocumentBlock, ...]:
        _require_unique((block.block_id for block in blocks), "block_id")
        return blocks


class ExclusionRecord(ContractModel):
    """Source material intentionally omitted from speech."""

    reason_code: Identifier
    description: NonEmptyText
    source: SourceLocation


class BookDocument(ContractModel):
    """Canonical output of source ingestion."""

    schema_version: Literal["book-document/v1"] = "book-document/v1"
    book_id: Identifier
    source_format: SourceFormat
    source_sha256: Sha256
    chapters: tuple[ChapterDocument, ...]
    exclusions: tuple[ExclusionRecord, ...] = ()
    warnings: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def chapters_are_ordered_and_unique(self) -> Self:
        _require_unique((chapter.chapter_id for chapter in self.chapters), "chapter_id")
        orders = [chapter.order for chapter in self.chapters]
        if orders != list(range(len(self.chapters))):
            raise ValueError("chapter order must be contiguous and start at zero")
        block_ids = [block.block_id for chapter in self.chapters for block in chapter.blocks]
        _require_unique(block_ids, "block_id across chapters")
        return self


class AppliedTransformation(ContractModel):
    """Auditable normalization change."""

    rule_id: Identifier
    before: NonEmptyText
    after: NonEmptyText


class NormalizedBlock(ContractModel):
    """A source block paired with deterministic spoken text."""

    block_id: Identifier
    display_text: NonEmptyText
    spoken_text: NonEmptyText
    transformations: tuple[AppliedTransformation, ...] = ()
    warnings: tuple[NonEmptyText, ...] = ()


class NormalizedDocument(ContractModel):
    """Versioned normalized text derived from a book document."""

    schema_version: Literal["normalized-document/v1"] = "normalized-document/v1"
    book_id: Identifier
    book_document_sha256: Sha256
    normalization_version: NonEmptyText
    lexicon_sha256: Sha256
    blocks: tuple[NormalizedBlock, ...]

    @field_validator("blocks")
    @classmethod
    def blocks_are_unique(cls, blocks: tuple[NormalizedBlock, ...]) -> tuple[NormalizedBlock, ...]:
        _require_unique((block.block_id for block in blocks), "block_id")
        return blocks


class PauseMetadata(ContractModel):
    """Assembly pause semantics kept outside synthesized audio."""

    break_before: BreakKind
    duration_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def none_has_zero_duration(self) -> Self:
        if self.break_before is BreakKind.NONE and self.duration_ms != 0:
            raise ValueError("a 'none' break must have zero duration")
        if self.break_before is not BreakKind.NONE and self.duration_ms == 0:
            raise ValueError("a structural break must have positive duration")
        return self


class ChunkRecord(ContractModel):
    """Stable, content-addressed synthesis unit."""

    chunk_id: Identifier
    chapter_id: Identifier
    paragraph_id: Identifier
    sentence_id: Identifier
    sequence: int = Field(ge=0)
    display_text: NonEmptyText
    spoken_text: NonEmptyText
    expected_language: Literal["it"] = "it"
    pause: PauseMetadata
    content_sha256: Sha256

    @model_validator(mode="after")
    def content_hash_matches(self) -> Self:
        if self.content_sha256 != self.compute_content_sha256():
            raise ValueError("content_sha256 does not match chunk content")
        return self

    def compute_content_sha256(self) -> str:
        """Hash generation-relevant chunk content."""

        return _chunk_content_sha256(
            chapter_id=self.chapter_id,
            paragraph_id=self.paragraph_id,
            sentence_id=self.sentence_id,
            spoken_text=self.spoken_text,
            expected_language=self.expected_language,
        )

    @classmethod
    def create(
        cls,
        *,
        chunk_id: str,
        chapter_id: str,
        paragraph_id: str,
        sentence_id: str,
        sequence: int,
        display_text: str,
        spoken_text: str,
        pause: PauseMetadata,
        expected_language: Literal["it"] = "it",
    ) -> Self:
        """Construct a chunk while deriving its content hash."""

        return cls(
            chunk_id=chunk_id,
            chapter_id=chapter_id,
            paragraph_id=paragraph_id,
            sentence_id=sentence_id,
            sequence=sequence,
            display_text=display_text,
            spoken_text=spoken_text,
            expected_language=expected_language,
            pause=pause,
            content_sha256=_chunk_content_sha256(
                chapter_id=chapter_id,
                paragraph_id=paragraph_id,
                sentence_id=sentence_id,
                spoken_text=spoken_text,
                expected_language=expected_language,
            ),
        )


class ChunkManifest(ContractModel):
    """Ordered chunks derived from normalized text."""

    schema_version: Literal["chunk-manifest/v1"] = "chunk-manifest/v1"
    book_id: Identifier
    normalized_document_sha256: Sha256
    chunks: tuple[ChunkRecord, ...]

    @model_validator(mode="after")
    def chunks_are_ordered_and_unique(self) -> Self:
        _require_unique((chunk.chunk_id for chunk in self.chunks), "chunk_id")
        sequences = [chunk.sequence for chunk in self.chunks]
        if sequences != list(range(len(self.chunks))):
            raise ValueError("chunk sequence must be contiguous and start at zero")
        return self


class ModelIdentity(ContractModel):
    """Exact synthesis engine and model revision."""

    engine: Identifier
    revision: NonEmptyText


class VoiceIdentity(ContractModel):
    """Stable identity for a named or reference-based voice."""

    voice_id: Identifier
    reference_sha256: Sha256 | None = None


class SynthesisSettings(ContractModel):
    """Generation parameters that can affect waveform output."""

    sample_rate_hz: int = Field(gt=0)
    seed: int
    speed: float = Field(default=1.0, gt=0)
    temperature: float | None = Field(default=None, ge=0)


class SynthesisIdentity(ContractModel):
    """Complete set of inputs used to address generated audio."""

    spoken_text: NonEmptyText
    normalization_version: NonEmptyText
    lexicon_sha256: Sha256
    model: ModelIdentity
    voice: VoiceIdentity
    settings: SynthesisSettings

    def cache_key(self) -> str:
        """Return the deterministic synthesis cache key."""

        return canonical_sha256(self)


class GenerationRecord(ContractModel):
    """Sidecar describing one generated WAV file."""

    schema_version: Literal["generation-record/v1"] = "generation-record/v1"
    chunk_id: Identifier
    chunk_content_sha256: Sha256
    identity: SynthesisIdentity
    cache_key: Sha256
    output_sha256: Sha256
    duration_ms: int = Field(gt=0)
    retry_number: int = Field(ge=0)

    @model_validator(mode="after")
    def cache_key_matches(self) -> Self:
        if self.cache_key != self.identity.cache_key():
            raise ValueError("cache_key does not match synthesis identity")
        return self


class GenerationManifest(ContractModel):
    """Generation sidecars associated with a chunk manifest."""

    schema_version: Literal["generation-manifest/v1"] = "generation-manifest/v1"
    book_id: Identifier
    chunk_manifest_sha256: Sha256
    records: tuple[GenerationRecord, ...]

    @field_validator("records")
    @classmethod
    def chunks_are_unique(
        cls, records: tuple[GenerationRecord, ...]
    ) -> tuple[GenerationRecord, ...]:
        _require_unique((record.chunk_id for record in records), "chunk_id")
        return records


class AlignmentEdit(ContractModel):
    """One human-readable ASR alignment difference."""

    operation: Literal["insert", "delete", "substitute"]
    expected: str
    actual: str


class VerificationRecord(ContractModel):
    """ASR and audio checks for one generated chunk."""

    schema_version: Literal["verification-record/v1"] = "verification-record/v1"
    chunk_id: Identifier
    generation_sha256: Sha256
    transcript: str
    wer: float = Field(ge=0)
    cer: float = Field(ge=0)
    alignment: tuple[AlignmentEdit, ...] = ()
    duration_ms: int = Field(gt=0)
    speaking_rate_wpm: float = Field(gt=0)
    reason_codes: tuple[Identifier, ...] = ()
    status: ReviewStatus


class VerificationManifest(ContractModel):
    """Verification results associated with generated records."""

    schema_version: Literal["verification-manifest/v1"] = "verification-manifest/v1"
    book_id: Identifier
    generation_manifest_sha256: Sha256
    records: tuple[VerificationRecord, ...]

    @field_validator("records")
    @classmethod
    def chunks_are_unique(
        cls, records: tuple[VerificationRecord, ...]
    ) -> tuple[VerificationRecord, ...]:
        _require_unique((record.chunk_id for record in records), "chunk_id")
        return records


def _require_unique(values: Iterable[str], label: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} values must be unique")


def _chunk_content_sha256(
    *,
    chapter_id: str,
    paragraph_id: str,
    sentence_id: str,
    spoken_text: str,
    expected_language: str,
) -> str:
    return canonical_sha256(
        {
            "chapter_id": chapter_id,
            "paragraph_id": paragraph_id,
            "sentence_id": sentence_id,
            "spoken_text": spoken_text,
            "expected_language": expected_language,
        }
    )
