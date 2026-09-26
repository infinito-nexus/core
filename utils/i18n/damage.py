"""Whether a translation broke something its source carried.

:func:`reason` is the single predicate both ends of the pipeline ask, and
:func:`harms` is its boolean face; the rest of this module are the criteria it
folds together.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from utils.i18n import names
from utils.i18n.repairs import resegment, tighten
from utils.i18n.spans import mask, matches, prose

MARKUP = '[]`*{}()"'
STRUCTURE = "[]{}`*()"
TRUNCATION_FLOOR = 120
TRUNCATION_RATIO = 0.5
ECHO_FLOOR = 30
STUTTER = re.compile(r"\b(\w+)(?:\s+\1\b){2,}", re.IGNORECASE | re.UNICODE)
WORDS = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
LATIN_FLOOR = 6
LATIN_SHARE = 0.9
NON_LATIN_SCRIPTS = frozenset(
    {
        "am",
        "ar",
        "be",
        "bg",
        "bn",
        "dv",
        "dz",
        "el",
        "fa",
        "gu",
        "he",
        "hi",
        "hy",
        "ja",
        "ka",
        "km",
        "kn",
        "ko",
        "ky",
        "lo",
        "mk",
        "ml",
        "mn",
        "mr",
        "my",
        "ne",
        "or",
        "pa",
        "ps",
        "ru",
        "si",
        "sr",
        "ta",
        "te",
        "th",
        "ti",
        "ug",
        "uk",
        "ur",
        "yi",
        "zh",
    }
)


def protected_spans(text: str) -> Counter:
    """Return the protected spans of ``text`` with their multiplicity.

    Args:
        text: a source message or its translation.
    """
    return Counter(text[start:end] for start, end in matches(text, with_names=False))


def missing_names(source: str, translation: str) -> set[str]:
    """Return the names ``source`` carries that ``translation`` dropped.

    Args:
        source: the source message.
        translation: what came back for it.
    """
    carried = {source[start:end] for start, end in names.spans(source)}
    return {name for name in carried if name not in translation}


def untranslated(translation: str, language: str) -> bool:
    """Return whether a non-Latin language came back written in Latin letters.

    The server answers with its input, lightly reworded, often enough that the
    result keeps every span and every markup character while still being
    English. Comparing scripts catches it wherever the target does not use the
    Latin one; for a Latin-script target it would need a language detector.

    Args:
        translation: what came back for the entry.
        language: ISO 639-1 code of the catalog being filled.
    """
    if language not in NON_LATIN_SCRIPTS:
        return False
    words = WORDS.findall(prose(translation))
    if len(words) < LATIN_FLOOR:
        return False
    latin = sum(1 for word in words if word.isascii())
    return latin / len(words) >= LATIN_SHARE


def stutters(source: str, translation: str) -> bool:
    """Return whether ``translation`` repeats a word the source does not.

    A server that loses its way answers ``Cloud`` with ``Cloud Cloud Cloud``.
    Every other rule passes it: the spans survive, the markup count survives,
    it is no echo, and ``truncated`` only watches the short side.

    Args:
        source: the source message.
        translation: what came back for it.
    """
    return bool(STUTTER.search(prose(translation))) and not STUTTER.search(
        prose(source)
    )


def truncated(source: str, translation: str) -> bool:
    """Return whether ``translation`` kept too little of ``source`` to be one.

    The floor keeps a short entry out: ``Situation`` becomes ``Lage`` and loses
    half its characters while saying the same thing. A passage past it that
    comes back halved has dropped a clause.

    Args:
        source: the source message.
        translation: what came back for it.
    """
    return (
        len(source) > TRUNCATION_FLOOR
        and len(translation) < len(source) * TRUNCATION_RATIO
    )


def structure(text: str) -> Counter:
    """Return the markup characters of ``text`` with their multiplicity.

    Args:
        text: a source message or its translation.
    """
    return Counter(character for character in text if character in STRUCTURE)


@dataclass(frozen=True)
class Rejected:
    """A translation that was turned down, kept so the catalog shows why.

    Args:
        text: what the server produced.
        reason: the criterion it broke.
    """

    text: str
    reason: str


def reason(source: str, translation: str, language: str = "") -> str:
    """Return the criterion ``translation`` broke, empty when it broke none.

    Single source of truth for both ends of the pipeline: the client drops a
    translation this rejects, and the release gate reports one that survived
    anyway. A check on one side only lets every run rewrite what the other
    side then condemns, which never converges.

    A translation identical to its source changed nothing and so damaged
    nothing, except when the source is a sentence: the server answers with its
    input when it fails, and the client seeds every entry with the source, so
    an echoed sentence is a failure that would otherwise count as translated
    and never be retried.

    Args:
        source: the source message.
        translation: what came back for it.
        language: ISO 639-1 code of the catalog, when the caller knows it. The
            script comparison is the one check that needs it; every other
            criterion reads both strings alone.
    """
    if translation == source:
        alphabetic = sum(character.isalpha() for character in prose(source))
        return "echo" if alphabetic >= ECHO_FLOOR else ""
    if protected_spans(translation) != protected_spans(source):
        return "protected-span"
    if missing_names(source, translation):
        return "missing-name"
    if stutters(source, translation):
        return "stutter"
    if untranslated(translation, language):
        return "untranslated"
    if truncated(source, translation):
        return "truncated"
    if structure(translation) != structure(source):
        return "structure"
    if tighten(translation) != translation:
        return "spacing"
    if resegment(translation, mask(source).spans, source) != translation:
        return "segmentation"
    return ""


def harms(source: str, translation: str, language: str = "") -> bool:
    """Return whether ``translation`` broke something ``source`` carried.

    Args:
        source: the source message.
        translation: what came back for it.
        language: ISO 639-1 code of the catalog, when the caller knows it.
    """
    return bool(reason(source, translation, language))
