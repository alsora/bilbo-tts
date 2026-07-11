from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bilbo_tts.config import LexiconConfig
from bilbo_tts.models import (
    BlockKind,
    BookDocument,
    ChapterDocument,
    DocumentBlock,
    SourceFormat,
    SourceLocation,
)
from bilbo_tts.normalization import (
    LexiconError,
    LoadedLexicons,
    load_lexicons,
    normalize_document,
)
from bilbo_tts.normalization.rules import apply_rules
from bilbo_tts.serialization import sha256_bytes


@pytest.fixture(scope="module")
def lexicons() -> LoadedLexicons:
    return load_lexicons(Path("."), ())


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Il rapporto è 60/40.", "Il rapporto è sessanta a quaranta."),
        ("Rende il 12,5%.", "Rende il dodici virgola cinque per cento."),
        ("Costa € 1.234,50.", "Costa milleduecentotrentaquattro euro e cinquanta centesimi."),
        ("Data 31/12/2024.", "Data trentuno dicembre duemilaventiquattro."),
        ("Vedi cap. 2.1.", "Vedi capitolo due punto uno."),
        ("Vedi appendice A.5.", "Vedi appendice a punto cinque."),
        ("Intervallo 3-5.", "Intervallo tre a cinque."),
        ("Valore -5 e 1,25.", "Valore meno cinque e uno virgola due cinque."),
        ("È il 3º anno.", "È il terzo anno."),
        ("ETF, BCE, BTP e drawdown.", "et effe, bi ci e, bi ti pi e dròdaun."),
        ("Un PDF.", "Un pi di effe."),
        ("Il dott. Bianchi, ecc.", "Il dottor Bianchi, eccetera"),
    ],
)
def test_required_golden_normalization_cases(
    source: str,
    expected: str,
    lexicons: LoadedLexicons,
) -> None:
    spoken, _, warnings = apply_rules(source, lexicons)

    assert spoken == expected
    assert warnings == ()


def test_normalization_is_idempotent_and_auditable(lexicons: LoadedLexicons) -> None:
    source = "L'ETF rende il 5%."

    first, transformations, _ = apply_rules(source, lexicons)
    second, second_transformations, _ = apply_rules(first, lexicons)

    assert second == first
    assert transformations
    assert second_transformations == ()
    assert [item.rule_id for item in transformations] == [
        "percentage",
        "lexicon.finance-it.acronimo-etf",
    ]


def test_unicode_cleanup_preserves_typographic_punctuation(
    lexicons: LoadedLexicons,
) -> None:
    source = "L’autore disse: “va bene”."

    spoken, transformations, warnings = apply_rules(source, lexicons)

    assert spoken == source
    assert transformations == ()
    assert warnings == ()


def test_unicode_cleanup_retains_non_punctuation_canonicalization(
    lexicons: LoadedLexicons,
) -> None:
    spoken, transformations, warnings = apply_rules("prima\u00a0dopo…", lexicons)

    assert spoken == "prima dopo..."
    assert [item.rule_id for item in transformations] == ["unicode-cleanup"]
    assert warnings == ()


def test_equation_rules_are_bounded_and_warn_for_unsupported_math(
    lexicons: LoadedLexicons,
) -> None:
    spoken, transformations, warnings = apply_rules(
        r"r = \frac{utile}{capitale}",
        lexicons,
        equation=True,
    )
    unsupported, _, unsupported_warnings = apply_rules(
        r"x^2 = y",
        lexicons,
        equation=True,
    )

    assert spoken == "erre uguale a utile diviso capitale"
    assert warnings == ()
    assert transformations[0].rule_id == "equation-fraction"
    assert unsupported == "ics^due uguale a ipsilon"
    assert unsupported_warnings == (
        "unresolved-math: unsupported equation notation remains in spoken text",
    )


def test_document_normalization_preserves_display_text_and_source_order(
    lexicons: LoadedLexicons,
) -> None:
    document = BookDocument(
        book_id="book",
        source_format=SourceFormat.LATEX,
        source_sha256="a" * 64,
        chapters=(
            ChapterDocument(
                chapter_id="chapter-1",
                order=0,
                title="Capitolo",
                blocks=(
                    DocumentBlock(
                        block_id="block-1",
                        kind=BlockKind.PARAGRAPH,
                        display_text="Rende il 5%.",
                        source=SourceLocation(source_path="source/main.tex"),
                    ),
                ),
            ),
        ),
    )

    normalized = normalize_document(
        document,
        book_document_sha256="c" * 64,
        normalization_version="it-v1",
        lexicons=lexicons,
    )

    assert normalized.blocks[0].display_text == "Rende il 5%."
    assert normalized.blocks[0].spoken_text == "Rende il cinque per cento."
    assert normalized.blocks[0].block_id == "block-1"


def test_configured_overlay_precedes_builtin_at_equal_priority(tmp_path: Path) -> None:
    payload = {
        "schema_version": "pronunciation-lexicon/v1",
        "lexicon_id": "model-overlay",
        "entries": [
            {
                "entry_id": "etf",
                "mode": "literal",
                "pattern": "ETF",
                "spoken": "e ti effe",
                "priority": 100,
                "case_sensitive": True,
                "word_boundaries": True,
            }
        ],
    }
    path = tmp_path / "overlay.yaml"
    data = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).encode()
    path.write_bytes(data)
    loaded = load_lexicons(
        tmp_path,
        (LexiconConfig(path="overlay.yaml", sha256=sha256_bytes(data)),),
    )

    spoken, transformations, _ = apply_rules("ETF", loaded)

    assert spoken == "e ti effe"
    assert transformations[0].rule_id == "lexicon.model-overlay.etf"


def test_lexicon_checksum_and_schema_are_validated(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "schema_version: pronunciation-lexicon/v1\n"
        "lexicon_id: bad\n"
        "entries:\n"
        "  - entry_id: bad\n"
        "    mode: regex\n"
        "    pattern: '('\n"
        "    spoken: bad\n",
        encoding="utf-8",
    )

    with pytest.raises(LexiconError, match="invalid regex"):
        load_lexicons(
            tmp_path,
            (LexiconConfig(path="bad.yaml", sha256=sha256_bytes(path.read_bytes())),),
        )
    path.write_text(
        "schema_version: pronunciation-lexicon/v1\nlexicon_id: empty\n", encoding="utf-8"
    )
    with pytest.raises(LexiconError, match="checksum mismatch"):
        load_lexicons(tmp_path, (LexiconConfig(path="bad.yaml", sha256="0" * 64),))
