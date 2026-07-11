"""Ordered, idempotent Italian text rules."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from decimal import Decimal
from typing import cast

from num2words import num2words  # type: ignore[import-untyped]

from bilbo_tts.models import AppliedTransformation
from bilbo_tts.normalization.lexicon import LoadedLexicons

RuleFunction = Callable[[str], str]

_MONTHS = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)
_LETTER_NAMES = {
    "a": "a",
    "b": "bi",
    "c": "ci",
    "d": "di",
    "e": "e",
    "f": "effe",
    "g": "gi",
    "h": "acca",
    "i": "i",
    "j": "i lunga",
    "k": "cappa",
    "l": "elle",
    "m": "emme",
    "n": "enne",
    "o": "o",
    "p": "pi",
    "q": "cu",
    "r": "erre",
    "s": "esse",
    "t": "ti",
    "u": "u",
    "v": "vi",
    "w": "doppia vu",
    "x": "ics",
    "y": "ipsilon",
    "z": "zeta",
}
_NUMBER = r"-?(?:(?:\d{1,3}(?:\.\d{3})+)(?:,\d+)?|\d+,\d+|\d+\.\d+|\d+)"


def apply_rules(
    text: str,
    lexicons: LoadedLexicons,
    *,
    equation: bool = False,
) -> tuple[str, tuple[AppliedTransformation, ...], tuple[str, ...]]:
    """Apply the stable rule sequence and report unresolved notation."""

    result = text
    transformations: list[AppliedTransformation] = []

    def apply(rule_id: str, function: RuleFunction) -> None:
        nonlocal result
        before = result
        result = function(result)
        if result != before:
            transformations.append(
                AppliedTransformation(rule_id=rule_id, before=before, after=result)
            )

    apply("unicode-cleanup", _unicode_cleanup)
    apply("dehyphenation", _dehyphenate)
    if equation:
        apply("equation-fraction", _equation_fractions)
        apply("equation-operators", _equation_operators)
        apply("equation-identifiers", _equation_identifiers)
    apply("date", _dates)
    apply("section-reference", _section_references)
    apply("range", _ranges)
    apply("percentage", _percentages)
    apply("currency", _currencies)
    apply("ratio", _ratios)
    apply("ordinal", _ordinals)
    apply("abbreviation", _abbreviations)
    apply("symbol", _symbols)

    before_lexicon = result
    result, lexicon_transformations = lexicons.apply(result)
    if result != before_lexicon:
        transformations.extend(lexicon_transformations)

    apply("acronym", _acronyms)
    apply("decimal", _decimals)
    apply("integer", _integers)
    apply("whitespace", _canonical_whitespace)

    warnings = _unresolved_warnings(result, equation=equation)
    return result, tuple(transformations), warnings


def _unicode_cleanup(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    return (
        normalized.replace("\u00ad", "")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("…", "...")
    )


def _dehyphenate(text: str) -> str:
    return re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=\w)", "", text)


def _equation_fractions(text: str) -> str:
    pattern = re.compile(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
    previous = ""
    while previous != text:
        previous = text
        text = pattern.sub(lambda match: f"{match.group(1)} diviso {match.group(2)}", text)
    return text


def _equation_operators(text: str) -> str:
    replacements = (
        (r"\\times|\\cdot|×|·|\*", " per "),
        (r"\\div|÷", " diviso "),
        (r"=", " uguale a "),
        (r"\+", " più "),
        (r"(?<!\d)-(?!\d)", " meno "),
        (r"/", " diviso "),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def _equation_identifiers(text: str) -> str:
    return re.sub(
        r"(?<!\w)([A-Za-z])(?!\w)",
        lambda match: _LETTER_NAMES[match.group(1).lower()],
        text,
    )


def _dates(text: str) -> str:
    pattern = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")

    def replace(match: re.Match[str]) -> str:
        day, month, year = (int(value) for value in match.groups())
        if not 1 <= day <= 31 or not 1 <= month <= 12:
            return match.group(0)
        day_spoken = "primo" if day == 1 else _number_words(day)
        return f"{day_spoken} {_MONTHS[month - 1]} {_number_words(year)}"

    return pattern.sub(replace, text)


def _section_references(text: str) -> str:
    labels = {
        "cap.": "capitolo",
        "capitolo": "capitolo",
        "sez.": "sezione",
        "sezione": "sezione",
        "par.": "paragrafo",
        "§": "paragrafo",
        "appendice": "appendice",
    }
    pattern = re.compile(
        r"(?<!\w)(cap\.|capitolo|sez\.|sezione|par\.|§|appendice)\s*"
        r"((?:[A-Za-z]|\d+)(?:\.\d+)*)(?!\w)",
        re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        label = labels[match.group(1).lower()]
        parts = " punto ".join(
            _number_words(int(part)) if part.isdigit() else _LETTER_NAMES[part.lower()]
            for part in match.group(2).split(".")
        )
        return f"{label} {parts}"

    return pattern.sub(replace, text)


def _ranges(text: str) -> str:
    pattern = re.compile(rf"(?<![\w/])({_NUMBER})\s*[–—-]\s*({_NUMBER})(?![\w/])")
    return pattern.sub(
        lambda match: f"{_number_token(match.group(1))} a {_number_token(match.group(2))}",
        text,
    )


def _percentages(text: str) -> str:
    pattern = re.compile(rf"(?<!\w)({_NUMBER})\s*%")
    return pattern.sub(lambda match: f"{_number_token(match.group(1))} per cento", text)


def _currencies(text: str) -> str:
    symbol_names = {
        "€": ("euro", "euro"),
        "$": ("dollaro", "dollari"),
        "£": ("sterlina", "sterline"),
    }
    after = re.compile(rf"(?<!\w)({_NUMBER})\s*([€$£])")
    before = re.compile(rf"([€$£])\s*({_NUMBER})(?!\w)")

    def spoken(amount: str, symbol: str) -> str:
        value = _parse_number(amount)
        singular, plural = symbol_names[symbol]
        unit = singular if abs(value) == 1 else plural
        whole = int(value)
        fraction = int((abs(value) - abs(whole)) * 100)
        result = f"{_number_words(whole)} {unit}"
        if fraction:
            cent_unit = "centesimo" if fraction == 1 else "centesimi"
            result = f"{result} e {_number_words(fraction)} {cent_unit}"
        return result

    text = after.sub(lambda match: spoken(match.group(1), match.group(2)), text)
    return before.sub(lambda match: spoken(match.group(2), match.group(1)), text)


def _ratios(text: str) -> str:
    pattern = re.compile(r"(?<!\d)(-?\d+)\s*/\s*(-?\d+)(?!\d)")
    return pattern.sub(
        lambda match: f"{_number_token(match.group(1))} a {_number_token(match.group(2))}",
        text,
    )


def _ordinals(text: str) -> str:
    pattern = re.compile(r"(?<!\w)(\d+)([º°ª])(?!\w)")

    def replace(match: re.Match[str]) -> str:
        spoken = cast(str, num2words(int(match.group(1)), lang="it", to="ordinal"))
        if match.group(2) == "ª" and spoken.endswith("o"):
            spoken = f"{spoken[:-1]}a"
        return spoken

    return pattern.sub(replace, text)


def _abbreviations(text: str) -> str:
    replacements = {
        r"(?<!\w)ecc\.(?!\w)": "eccetera",
        r"(?<!\w)dott\.(?!\w)": "dottor",
        r"(?<!\w)prof\.(?!\w)": "professor",
        r"(?<!\w)art\.(?=\s*\d)": "articolo ",
        r"(?<!\w)n\.(?=\s*\d)": "numero ",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _symbols(text: str) -> str:
    replacements = {"&": " e ", "+": " più ", "=": " uguale a "}
    for symbol, replacement in replacements.items():
        text = text.replace(symbol, replacement)
    return text


def _acronyms(text: str) -> str:
    return re.sub(
        r"(?<!\w)([A-Z]{2,6})(?!\w)",
        lambda match: " ".join(_LETTER_NAMES[letter.lower()] for letter in match.group(1)),
        text,
    )


def _decimals(text: str) -> str:
    pattern = re.compile(r"(?<!\w)-?\d+[,.]\d+(?!\w)")
    return pattern.sub(lambda match: _number_token(match.group(0)), text)


def _integers(text: str) -> str:
    return re.sub(
        r"(?<![\w.,])-?\d+(?![\w.,])",
        lambda match: _number_token(match.group(0)),
        text,
    )


def _number_token(token: str) -> str:
    return _number_words(_parse_number(token))


def _parse_number(token: str) -> Decimal:
    normalized = token.strip()
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", normalized):
        normalized = normalized.replace(".", "")
    return Decimal(normalized)


def _number_words(value: int | Decimal) -> str:
    if isinstance(value, Decimal) and value != value.to_integral():
        integral, fractional = format(value, "f").split(".", maxsplit=1)
        fractional = fractional.rstrip("0")
        sign = "meno " if integral.startswith("-") else ""
        absolute_integral = abs(int(integral))
        digits = " ".join(_number_words(int(digit)) for digit in fractional)
        return f"{sign}{_number_words(absolute_integral)} virgola {digits}"
    return cast(str, num2words(value, lang="it"))


def _canonical_whitespace(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n+ *", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def _unresolved_warnings(text: str, *, equation: bool) -> tuple[str, ...]:
    warnings: list[str] = []
    if equation and (re.search(r"\\[A-Za-z]+|[{}_^]", text) is not None):
        warnings.append("unresolved-math: unsupported equation notation remains in spoken text")
    symbols = "".join(sorted(set(re.findall(r"[<>@#%€$£]", text))))
    if symbols:
        warnings.append(f"unresolved-symbols: {symbols}")
    return tuple(warnings)
