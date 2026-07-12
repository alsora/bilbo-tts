from __future__ import annotations

import re
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
from bilbo_tts.normalization.lexicon import SHARED_LEXICON_DIR
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
        ("Rende lo 0,25%.", "Rende lo zero virgola venticinque per cento."),
        ("Rende lo 0,025%.", "Rende lo zero virgola zero venticinque per cento."),
        ("Costa € 1.234,50.", "Costa milleduecentotrentaquattro euro e cinquanta centesimi."),
        ("Data 31/12/2024.", "Data trentuno dicembre duemilaventiquattro."),
        ("Vedi cap. 2.1.", "Vedi capitolo due punto uno."),
        ("Vedi appendice A.5.", "Vedi appendice a punto cinque."),
        ("Intervallo 3-5.", "Intervallo tre a cinque."),
        ("Valore -5 e 1,25.", "Valore meno cinque e uno virgola venticinque."),
        ("È il 3º anno.", "È il terzo anno."),
        ("ETF, BCE, BTP e drawdown.", "et effe, bi ci e, bi ti pi e dròdaun."),
        ("L’INPS gestisce la previdenza.", "L’inps gestisce la previdenza."),
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


def test_reviewed_acronyms_distinguish_word_and_letter_pronunciation(
    lexicons: LoadedLexicons,
) -> None:
    spoken, transformations, warnings = apply_rules("INPS ed ETF.", lexicons)

    assert spoken == "inps ed et effe."
    assert warnings == ()
    assert {item.rule_id for item in transformations} == {
        "lexicon.finance-it.acronimo-inps",
        "lexicon.finance-it.acronimo-etf",
    }


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
        r"\sqrt{x} = y",
        lexicons,
        equation=True,
    )

    assert spoken == "erre uguale a utile diviso capitale"
    assert warnings == ()
    assert transformations[0].rule_id == "equation-fraction"
    assert unsupported == r"\sqrt{ics} uguale a ipsilon"
    assert unsupported_warnings == (
        "unresolved-math: unsupported equation notation remains in spoken text",
    )


@pytest.mark.parametrize(
    ("source", "expected", "equation"),
    [
        (
            r"\begin{equation} C_n = C_0 \times r^n "
            r"\label{eq:capitalizzazione} \end{equation}",
            "ci con pedice enne uguale a ci con pedice zero per erre elevato alla enne",
            True,
        ),
        (
            r"\text{Valore atteso}\quad \approx 99{,}75",
            "Valore atteso circa uguale a novantanove virgola settantacinque",
            True,
        ),
        (
            r"C_0\,\rightarrow\quad C_n; 100 \div 4",
            "ci con pedice zero porta a ci con pedice enne; cento diviso quattro",
            True,
        ),
        (
            r"15.000--100.000 \euro",
            "quindicimila a centomila euro",
            False,
        ),
        (
            r"35--40\%",
            "trentacinque a quaranta per cento",
            False,
        ),
        ("miliardi di €", "miliardi di euro", False),
        ("50/30/20", "cinquanta a trenta a venti", False),
    ],
)
def test_latex_regressions_from_selected_chapters(
    source: str,
    expected: str,
    equation: bool,
    lexicons: LoadedLexicons,
) -> None:
    spoken, _, warnings = apply_rules(source, lexicons, equation=equation)
    repeated, repeated_transformations, repeated_warnings = apply_rules(
        spoken,
        lexicons,
        equation=equation,
    )

    assert spoken == expected
    assert warnings == ()
    assert re.search(r"[\\{}%€]", spoken) is None
    assert repeated == spoken
    assert repeated_transformations == ()
    assert repeated_warnings == ()


def test_unsupported_latex_remains_visible_and_warned(
    lexicons: LoadedLexicons,
) -> None:
    source = r"Formula \sqrt{capitale}"

    spoken, _, warnings = apply_rules(source, lexicons)

    assert spoken == source
    assert warnings == ("unresolved-math: unsupported equation notation remains in spoken text",)


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


def test_shared_scope_loads_from_repository_lexicon_directory(tmp_path: Path) -> None:
    shared_path = SHARED_LEXICON_DIR / "kokoro-it.yaml"
    checksum = sha256_bytes(shared_path.read_bytes())

    loaded = load_lexicons(
        tmp_path,
        (LexiconConfig(path="kokoro-it.yaml", sha256=checksum, scope="shared"),),
    )

    assert loaded.lexicons[1].source == "shared:kokoro-it.yaml"
    spoken, transformations, _ = apply_rules("La duration conta.", loaded)
    assert spoken == "La durèscion conta."
    assert transformations[0].rule_id == "lexicon.kokoro-it.loanword-duration"
    spoken, transformations, _ = apply_rules("Zero virgola venticinque.", loaded)
    assert spoken == "dzzèro virgola venticinque."
    assert transformations[0].rule_id == "lexicon.kokoro-it.consonant-zero"
    corrections = (
        ("Principi", "princìpi", "homograph-principi"),
        ("Wall Street", "uòl strìtt", "loanword-wall-street"),
        ("riflettere", "riflèttere", "vowel-riflettere"),
        ("siano", "sìano", "stress-siano"),
        ("maggior", "maggiór", "stress-maggior"),
        ("vedremo", "vedrémo", "vowel-vedremo"),
        ("ordine", "órdine", "vowel-ordine"),
        ("costosi", "costósi", "vowel-costosi"),
        ("azienda", "ad-ziènda", "consonant-azienda"),
        ("aziende", "ad-ziènde", "consonant-aziende"),
    )
    for source, expected, entry_id in corrections:
        spoken, transformations, _ = apply_rules(source, loaded)
        assert spoken == expected
        assert transformations[0].rule_id == f"lexicon.kokoro-it.{entry_id}"


def test_shared_scope_rejects_paths_escaping_the_lexicon_directory(tmp_path: Path) -> None:
    # Bypass model validation to exercise the loader's own escape guard.
    escape = LexiconConfig.model_construct(
        path="inner/../../secrets.yaml",
        sha256="0" * 64,
        scope="shared",
    )

    with pytest.raises(LexiconError, match="escapes the shared directory"):
        load_lexicons(tmp_path, (escape,))


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
