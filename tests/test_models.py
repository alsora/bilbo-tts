from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bilbo_tts.models import (
    AlignmentEdit,
    AppliedTransformation,
    BackendIdentity,
    BlockKind,
    BookDocument,
    BreakKind,
    ChapterDocument,
    ChunkManifest,
    ChunkRecord,
    ContractModel,
    DocumentBlock,
    GenerationManifest,
    GenerationRecord,
    ManualReviewDecision,
    ModelIdentity,
    NormalizedBlock,
    NormalizedDocument,
    PauseMetadata,
    ReviewStatus,
    SourceFormat,
    SourceLocation,
    SynthesisIdentity,
    SynthesisSettings,
    VerificationHeuristics,
    VerificationManifest,
    VerificationRecord,
    VoiceIdentity,
)
from bilbo_tts.serialization import canonical_json_bytes, canonical_sha256

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def make_manifests() -> tuple[
    BookDocument,
    NormalizedDocument,
    ChunkManifest,
    GenerationManifest,
    VerificationManifest,
]:
    book = BookDocument(
        book_id="finance-book",
        source_format=SourceFormat.LATEX,
        source_sha256=HASH_A,
        chapters=(
            ChapterDocument(
                chapter_id="chapter-1",
                order=0,
                title="Capitolo uno",
                blocks=(
                    DocumentBlock(
                        block_id="block-1",
                        kind=BlockKind.PARAGRAPH,
                        display_text="Il rendimento è 5%.",
                        source=SourceLocation(
                            source_path="source/book.tex",
                            start_line=10,
                            end_line=10,
                        ),
                    ),
                ),
            ),
        ),
    )
    normalized = NormalizedDocument(
        book_id=book.book_id,
        book_document_sha256=canonical_sha256(book),
        normalization_version="it-v1",
        lexicon_sha256=HASH_B,
        blocks=(
            NormalizedBlock(
                block_id="block-1",
                display_text="Il rendimento è 5%.",
                spoken_text="Il rendimento è cinque per cento.",
                transformations=(
                    AppliedTransformation(
                        rule_id="percentage",
                        before="5%",
                        after="cinque per cento",
                    ),
                ),
            ),
        ),
    )
    chunk = ChunkRecord.create(
        chunk_id="chunk-1",
        chapter_id="chapter-1",
        paragraph_id="block-1",
        sentence_id="sentence-1",
        sequence=0,
        display_text="Il rendimento è 5%.",
        spoken_text="Il rendimento è cinque per cento.",
        pause=PauseMetadata(break_before=BreakKind.CHAPTER, duration_ms=1500),
    )
    chunks = ChunkManifest(
        book_id=book.book_id,
        normalized_document_sha256=canonical_sha256(normalized),
        chunks=(chunk,),
    )
    identity = SynthesisIdentity(
        spoken_text=chunk.spoken_text,
        normalization_version=normalized.normalization_version,
        model=ModelIdentity(engine="fake", revision="model-revision"),
        backend=BackendIdentity(
            backend="stdlib",
            model_id="bilbo-tts/fake",
            inference_parameters={"mode": "test"},
        ),
        voice=VoiceIdentity(voice_id="narrator", reference_sha256=HASH_C),
        settings=SynthesisSettings(sample_rate_hz=24_000, seed=7),
    )
    generation_record = GenerationRecord(
        chunk_id=chunk.chunk_id,
        chunk_content_sha256=chunk.content_sha256,
        identity=identity,
        cache_key=identity.cache_key(),
        output_path="audio/chunk-1/output.wav",
        output_sha256=HASH_A,
        sample_rate_hz=24_000,
        frame_count=52_800,
        duration_ms=2200,
        retry_number=0,
    )
    generations = GenerationManifest(
        book_id=book.book_id,
        chunk_manifest_sha256=canonical_sha256(chunks),
        records=(generation_record,),
    )
    verification = VerificationManifest(
        book_id=book.book_id,
        generation_manifest_sha256=canonical_sha256(generations),
        verification_config_sha256=HASH_C,
        asr_model_id="test/whisper",
        asr_model_revision="test-revision",
        records=(
            VerificationRecord(
                chunk_id=chunk.chunk_id,
                generation_sha256=canonical_sha256(generation_record),
                attempt_number=0,
                transcript="Il rendimento è cinque percento.",
                wer=0.2,
                cer=0.05,
                alignment=(
                    AlignmentEdit(
                        operation="substitute",
                        expected="per cento",
                        actual="percento",
                    ),
                ),
                duration_ms=2200,
                speaking_rate_wpm=145.0,
                heuristics=VerificationHeuristics(
                    missing_prefix_words=0,
                    missing_suffix_words=0,
                    repeated_ngram_count=0,
                    silence_ratio=0.1,
                    clipped_sample_ratio=0,
                    peak_dbfs=-3,
                ),
                reason_codes=("minor-asr-difference",),
                status=ReviewStatus.ACCEPTED,
            ),
        ),
    )
    return book, normalized, chunks, generations, verification


@pytest.mark.parametrize("manifest", make_manifests())
def test_manifest_round_trip_is_canonical(manifest: ContractModel) -> None:
    model_type = type(manifest)
    serialized = canonical_json_bytes(manifest)

    restored = model_type.model_validate_json(serialized)

    assert restored == manifest
    assert canonical_json_bytes(restored) == serialized
    assert canonical_sha256(restored) == canonical_sha256(manifest)


def test_canonical_serialization_is_stable_across_mapping_order() -> None:
    assert canonical_json_bytes({"z": 1, "a": "è"}) == canonical_json_bytes({"a": "è", "z": 1})
    assert json.loads(canonical_json_bytes({"text": "è"})) == {"text": "è"}


def test_unknown_contract_fields_are_rejected() -> None:
    book = make_manifests()[0]
    payload = book.model_dump(mode="json")
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BookDocument.model_validate(payload)


def test_manual_verification_decision_is_explicit_and_status_bound() -> None:
    record = make_manifests()[-1].records[0]
    decision = ManualReviewDecision(
        action="accept",
        reviewer="human-reviewer",
        note="Listened to the complete chunk.",
    )

    accepted = record.model_copy(
        update={
            "status": ReviewStatus.ACCEPTED,
            "reason_codes": (*record.reason_codes, "manual-accept"),
            "manual_decision": decision,
            "heuristics": VerificationHeuristics(
                missing_prefix_words=0,
                missing_suffix_words=0,
                repeated_ngram_count=0,
                silence_ratio=0.2,
                clipped_sample_ratio=0,
                peak_dbfs=-3,
            ),
        }
    )

    assert VerificationRecord.model_validate(accepted.model_dump()) == accepted
    with pytest.raises(ValidationError, match="requires status"):
        VerificationRecord.model_validate(
            {
                **accepted.model_dump(),
                "status": ReviewStatus.REVIEW,
            }
        )


def test_book_rejects_duplicate_blocks_and_noncontiguous_chapters() -> None:
    block = make_manifests()[0].chapters[0].blocks[0]

    with pytest.raises(ValidationError, match="block_id values must be unique"):
        ChapterDocument(
            chapter_id="chapter-1",
            order=0,
            title="Duplicate",
            blocks=(block, block),
        )
    with pytest.raises(ValidationError, match="chapter order must be contiguous"):
        BookDocument(
            book_id="book",
            source_format=SourceFormat.PDF,
            source_sha256=HASH_A,
            chapters=(
                ChapterDocument(
                    chapter_id="chapter-2",
                    order=1,
                    title="Wrong order",
                    blocks=(block,),
                ),
            ),
        )


def test_source_location_and_pause_invariants_are_enforced() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        SourceLocation(source_path="book.tex", start_line=1)
    with pytest.raises(ValidationError, match="must not precede"):
        SourceLocation(source_path="book.tex", start_line=2, end_line=1)
    with pytest.raises(ValidationError, match="must have zero duration"):
        PauseMetadata(break_before=BreakKind.NONE, duration_ms=1)
    with pytest.raises(ValidationError, match="must have positive duration"):
        PauseMetadata(break_before=BreakKind.PARAGRAPH, duration_ms=0)


def test_chunk_and_generation_reject_mismatched_hashes() -> None:
    chunk = make_manifests()[2].chunks[0]
    payload = chunk.model_dump()
    payload["spoken_text"] = "Testo diverso."

    with pytest.raises(ValidationError, match="content_sha256 does not match"):
        ChunkRecord.model_validate(payload)

    record = make_manifests()[3].records[0]
    generation_payload = record.model_dump()
    generation_payload["cache_key"] = HASH_B
    with pytest.raises(ValidationError, match="cache_key does not match"):
        GenerationRecord.model_validate(generation_payload)


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("spoken_text", "Testo cambiato."),
        ("normalization_version", "it-v2"),
        ("model", ModelIdentity(engine="fake", revision="new-revision")),
        (
            "backend",
            BackendIdentity(
                backend="stdlib",
                model_id="bilbo-tts/fake",
                inference_parameters={"mode": "changed"},
            ),
        ),
        ("voice", VoiceIdentity(voice_id="other-voice")),
        ("settings", SynthesisSettings(sample_rate_hz=48_000, seed=8)),
    ],
)
def test_generation_inputs_change_cache_key(field: str, replacement: object) -> None:
    identity = make_manifests()[3].records[0].identity
    changed = identity.model_copy(update={field: replacement})

    assert changed.cache_key() != identity.cache_key()


def test_presentation_metadata_does_not_affect_cache_key() -> None:
    identity = make_manifests()[3].records[0].identity

    first_metadata = {"title": "Titolo A", "author": "Autore"}
    second_metadata = {"title": "Titolo B", "author": "Altro autore"}

    assert first_metadata != second_metadata
    assert identity.cache_key() == identity.model_copy().cache_key()
