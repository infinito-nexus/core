"""Whether a translation broke something its source carried.

:func:`reason` is the single predicate both ends of the pipeline ask, and
:func:`harms` is its boolean face; the rest of this module are the criteria it
folds together.

``WORDS`` takes one character as one word in Han, Kana, Thai, Lao, Khmer and
Myanmar, which write without separators. Its single-character branch has to
come first, or the run branch swallows a whole sentence together with the
Latin product names inside it and returns one token whose Latin share decides
the verdict alone. ``UNSPACED_RANGES`` holds codepoints rather than escapes
because a formatter rewrites an escape into the character it names, and the
literal blob that leaves behind cannot be read or reviewed.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from itertools import groupby

from utils.cache.files import PROJECT_ROOT
from utils.i18n import names
from utils.i18n.languages import (
    language_scripts,
    latin_share,
    non_latin_languages,
    script,
)
from utils.i18n.repairs import resegment, tighten
from utils.i18n.spans import PRINTF, mask, matches, prose

MARKUP = '[]`*{}()"'
STRUCTURE = "[]{}`*()"
TRUNCATION_FLOOR = 120
TRUNCATION_RATIO = 0.5
DENSE_TRUNCATION_RATIO = 0.25
DENSE_SCRIPTS = frozenset({"ja", "ko", "zh"})
COLLAPSE_FLOOR = 40
COLLAPSE_RATIO = 0.15
MAX_SHARING_SOURCES = 2
ECHO_FLOOR = 30
STUTTER = re.compile(r"\b(\w+)(?:\s+\1\b){2,}", re.IGNORECASE | re.UNICODE)
UNSPACED_RANGES = (
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x0E00, 0x0E7F),
    (0x0E80, 0x0EFF),
    (0x1780, 0x17FF),
    (0x1000, 0x109F),
)
UNSPACED = "".join(f"{chr(low)}-{chr(high)}" for low, high in UNSPACED_RANGES)
WORDS = re.compile(rf"[{UNSPACED}]|[^\W\d_]{{2,}}", re.UNICODE)
LATIN_SHARE = 0.9
NON_LATIN_SCRIPTS = non_latin_languages(PROJECT_ROOT)
SCRIPT_SHARE = 0.5
LATIN = "LATIN"
LANGUAGE_SCRIPTS = language_scripts(PROJECT_ROOT)
WRITTEN_SCRIPTS = frozenset(LANGUAGE_SCRIPTS.values()) - {LATIN}


def protected_spans(text: str) -> Counter:
    """Return the protected spans of ``text`` with their multiplicity.

    Args:
        text: a source message or its translation.
    """
    return Counter(text[start:end] for start, end in matches(text, with_names=False))


ADDED = re.compile(
    rf"{PRINTF}"
    r"|\{\{|\{%|\{[A-Za-z_]\w*\}"
    r"|<[^<>\s]+>"
    r"|[\U0001F300-\U0001FAFF☀-➿️]"
)


def added_spans(source: str, translation: str) -> Counter:
    """Return the spans ``translation`` invented whose presence is itself damage.

    ``PROTECTED`` claims every digit run and every bare markup character,
    because over-claiming is right when masking. As a comparison basis it is
    not: the translation is another language whose ordinary prose trips those
    same rules, and a gained parenthesis breaks nothing the source carried.
    What does break something is an invented placeholder - an injected ``%s``
    fails ``msgfmt``, a decoder artefact like ``♪`` or a leaked ``<unk>`` is
    garbage - so only those keep a surplus refused.

    Args:
        source: the source message.
        translation: what came back for it.
    """
    surplus = protected_spans(translation) - protected_spans(source)
    return Counter({span: n for span, n in surplus.items() if ADDED.search(span)})


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

    There is no length floor. :func:`verdict` reaches this only once an exact
    echo is ruled out, so Latin text that differs from the source cannot be a
    term the language keeps in English. The catalogs are mostly one- to
    four-word labels, which is where the wrong language hid for as long as a
    six-word floor stood here.

    The ratio is only as good as the word count, which is why ``WORDS`` splits
    a separator-less script per character: a Japanese sentence carrying two
    Latin product names is one token to a run-based pattern, and one token
    whose Latin share passes a half makes the ratio 1.0 on a sound
    translation.

    Args:
        translation: what came back for the entry.
        language: ISO 639-1 code of the catalog being filled.
    """
    if language not in NON_LATIN_SCRIPTS:
        return False
    words = WORDS.findall(prose(translation))
    if not words:
        return False
    latin = sum(1 for word in words if (latin_share(word) or 0) > 0.5)
    return latin / len(words) >= LATIN_SHARE


def foreign_script(translation: str, language: str) -> bool:
    """Return whether a Latin-script language came back in another script.

    The mirror of :func:`untranslated`, and the half that catches a model
    answering a language it cannot write with one it can: Chamorro came back
    in Han because the code ``ch`` reads as Chinese, Turkish in Bengali,
    Avestan in Arabic. A target that writes its own name in Latin letters has
    no business returning a line that carries almost none.

    Args:
        translation: what came back for the entry.
        language: ISO 639-1 code of the catalog being filled.
    """
    if language in NON_LATIN_SCRIPTS:
        return False
    words = WORDS.findall(prose(translation))
    if not words:
        return False
    latin = sum(1 for word in words if (latin_share(word) or 0) > 0.5)
    return latin / len(words) <= 1 - LATIN_SHARE


def wrong_script(source: str, translation: str, language: str = "") -> bool:
    """Return whether a non-Latin language came back mostly in another non-Latin script.

    Args:
        source: the source message.
        translation: what came back for it.
        language: ISO 639-1 code of the catalog being filled.

    Returns:
        True when fewer than ``SCRIPT_SHARE`` of the letters the translation
        writes in a script of :data:`WRITTEN_SCRIPTS` the source does not
        carry belong to the language's own script. A word of a single letter
        is not counted.
    """
    if language not in NON_LATIN_SCRIPTS:
        return False
    carried = {script(char) for char in prose(source) if char.isalpha()}
    written = []
    for word in spelled_words(prose(translation)):
        letters = [script(char) for char in word if char.isalpha()]
        if len(letters) > 1:
            written += [
                name
                for name in letters
                if name in WRITTEN_SCRIPTS and name not in carried
            ]
    if not written:
        return False
    own = LANGUAGE_SCRIPTS[language]
    return sum(1 for name in written if name == own) / len(written) < SCRIPT_SHARE


def spelled_words(text: str) -> list[str]:
    """Return the runs of letters and combining marks in ``text``.

    Args:
        text: any text.
    """
    return [
        "".join(run)
        for spelled, run in groupby(
            text,
            key=lambda char: char.isalpha() or unicodedata.category(char)[0] == "M",
        )
        if spelled
    ]


def added_lines(source: str, translation: str) -> bool:
    """Return whether ``translation`` breaks more lines than ``source``.

    Args:
        source: the source message.
        translation: what came back for it.
    """
    return translation.count("\n") > source.count("\n")


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


def truncated(source: str, translation: str, language: str = "") -> bool:
    """Return whether ``translation`` kept too little of ``source`` to be one.

    The floor keeps a short entry out: ``Situation`` becomes ``Lage`` and loses
    half its characters while saying the same thing. A passage past it that
    comes back halved has dropped a clause.

    A logographic target needs its own ratio: one character carries a whole
    morpheme, so a complete rendering runs at a third of the source's length and
    the flat ratio reads it as a dropped clause. Measured against the live
    engine, 36 of 45 complete zh/ja/ko passages tripped it, 44 of those 45
    ending in terminal punctuation; the shortest was 0.28.

    Args:
        source: the source message.
        translation: what came back for it.
        language: ISO 639-1 code of the catalog, when the caller knows it.
    """
    ratio = DENSE_TRUNCATION_RATIO if language in DENSE_SCRIPTS else TRUNCATION_RATIO
    return len(source) > TRUNCATION_FLOOR and len(translation) < len(source) * ratio


def collapsed(source: str, translation: str) -> bool:
    """Return whether ``translation`` is a fragment rather than a rendering.

    A server that gives up on a passage answers it with a label: four distinct
    sentences all come back as ``Name``. ``truncated`` does not see it, because
    its floor starts where these sources end, and every other rule passes: a
    label carries no span, no name, no markup and no stutter.

    The ratio sits far below ``TRUNCATION_RATIO`` so that a language which
    genuinely says the same in fewer characters survives it. Chinese renders a
    58-character source in 17, which is a fifth of the source and twice this
    floor; the label that prompted the rule is a fifteenth.

    Args:
        source: the source message.
        translation: what came back for it.
    """
    return (
        len(source) > COLLAPSE_FLOOR and len(translation) < len(source) * COLLAPSE_RATIO
    )


def echoes(source: str, translation: str) -> bool:
    """Return whether the translation carries its whole source and continues.

    A server that answers ``<source>\\n---\\n<rendering>`` passes every other
    rule: the rendering it appended keeps the spans, the names and the markup,
    and the separator is made of characters ``structure`` does not count. The
    reader is then served the English text as its own translation.

    The floor is the one :func:`reason` applies to a plain echo, because the
    risk it guards against is the same: a short source legitimately survives
    inside a longer rendering, a sentence does not.

    Args:
        source: the source message.
        translation: what came back for it.
    """
    if source not in translation:
        return False
    return sum(character.isalpha() for character in prose(source)) >= ECHO_FLOOR


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
    if echoes(source, translation):
        return "echo"
    if added_lines(source, translation):
        return "added-line"
    if protected_spans(source) - protected_spans(translation):
        return "protected-span"
    if added_spans(source, translation):
        return "added-span"
    if missing_names(source, translation):
        return "missing-name"
    if stutters(source, translation):
        return "stutter"
    if untranslated(translation, language):
        return "untranslated"
    if foreign_script(translation, language):
        return "foreign-script"
    if wrong_script(source, translation, language):
        return "wrong-script"
    if truncated(source, translation, language):
        return "truncated"
    if collapsed(source, translation):
        return "collapsed"
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
