"""Protection of the parts of a message that machine translation must not touch."""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass

from utils.i18n import names

PRINTF = r"%\([A-Za-z_]\w*\)[sdif]|%[sdif]"
PLACEHOLDER = re.compile(PRINTF)

PROTECTED = re.compile(
    r"``.+?``"
    r"|:[\w.+-]+:`[^`]+`"
    r"|`[^`]+`_{0,2}"
    r"|\{\{.+?\}\}"
    r"|\{%.+?%\}"
    r"|\{\{.*"
    r"|\{[A-Za-z_]\w*\}"
    rf"|{PRINTF}"
    r"|https?://(?:[^\s<>\"'`()\[\]]|\([^\s<>\"'`()]*\))+"
    r"|<[^<>\s]+>"
    r"|(?<=\])\((?:[^\s()]|\([^\s()]*\))+\)"
    r"|(?<![\w/@.-])[\w.-]+/[\w.@+-]+(?:/[\w.@+-]+)+"
    r"|(?<![\w/@.-])[\w.-]+/[\w.@+-]*\.[A-Za-z]\w{0,7}\b"
    r"|\b[A-Za-z]\w*(?:\.[A-Za-z]\w+)+"
    r"|\b[A-Za-z]\w*_\w+"
    r"|\"[\w.-]*(?:<[^>\s]*>[\w.-]*)*\"|'[\w.-]*(?:<[^>\s]*>[\w.-]*)*'"
    r"|\d+(?:[.,]\d+)*"
    r"|\*\*|\*|`|\[|\]|\{|\}|\(|\)|\""
)


def carries_placeholder(message_id: str | tuple[str, ...]) -> bool:
    """Return whether ``message_id`` holds a printf placeholder a translation must keep.

    Args:
        message_id: a catalog message id, singular or a plural tuple.
    """
    forms = message_id if isinstance(message_id, tuple) else (message_id,)
    return any(PLACEHOLDER.search(form) for form in forms)


EXTRA = re.compile(
    r"[\U0001F300-\U0001FAFF☀-➿️]"
    r"|[\w.+-]+@[\w-]+\.[\w.]+"
)


def matches(text: str, with_names: bool = True) -> list[tuple[int, int]]:
    """Return the non-overlapping offsets every protection rule claims.

    Args:
        text: a source message or its translation.
        with_names: whether role names and titles take part. They do when a
            request is masked, so the translator never sees them, and they do
            not when two texts are compared: German capitalises every noun, so
            the lowercase ``shell extensions`` becomes ``Shell-Erweiterungen``
            and a set comparison would read the capital as a surplus span.
    """
    found = [(m.start(), m.end()) for m in PROTECTED.finditer(text)]
    found += [(m.start(), m.end()) for m in EXTRA.finditer(text)]
    if with_names:
        found += names.spans(text)
    kept: list[tuple[int, int]] = []
    reach = 0
    for start, end in sorted(found):
        if start < reach:
            continue
        kept.append((start, end))
        reach = end
    return kept


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
        "am", "ar", "be", "bg", "bn", "dv", "dz", "el", "fa", "gu", "he", "hi",
        "hy", "ja", "ka", "km", "kn", "ko", "ky", "lo", "mk", "ml", "mn", "mr",
        "my", "ne", "or", "pa", "ps", "ru", "si", "sr", "ta", "te", "th", "ti",
        "ug", "uk", "ur", "yi", "zh",
    }
)
EMPHASIS = re.compile(r"(\*\*)[ \t]*([^\s]|[^\s].*?[^\s])[ \t]*\1", re.DOTALL)


def resegment(restored: str, spans: tuple[str, ...], source: str) -> str:
    """Put back the sentence boundary a translator dropped behind a protected span.

    A name is skipped. Every other protected span ends in a delimiter, so a
    letter right behind it can only be the text the boundary was lost from, but
    a name ends in a word character and an agglutinative language suffixes it:
    ``Baserow`` is found inside the Bengali ``Baserowo`` and the punctuation
    would land inside the word.

    Args:
        restored: the translation with every protected span put back.
        spans: the protected spans of the source.
        source: the source message, which holds the boundary that went missing.
    """
    named = {source[start:end] for start, end in names.spans(source)}
    for span in spans:
        if span in named:
            continue
        start = source.find(span)
        if start < 0:
            continue
        boundary = source[start + len(span) : start + len(span) + 2]
        if len(boundary) != 2 or boundary[0] not in ".,;:" or not boundary[1].isspace():
            continue
        follows = restored.find(span) + len(span)
        if follows > len(span) - 1 and restored[follows : follows + 1].isalpha():
            restored = restored[:follows] + boundary[0] + " " + restored[follows:]
    return restored


def tighten(restored: str) -> str:
    """Return ``restored`` with the whitespace a translator set inside emphasis removed.

    Args:
        restored: the translation with every protected span put back.
    """
    return EMPHASIS.sub(
        lambda pair: pair.group(1) + pair.group(2) + pair.group(1), restored
    )


TERMINATORS = ".!?"
RUN_OF_SPACES = re.compile(r"[ \t]{2,}")


def collapse(restored: str, source: str) -> str:
    """Return ``restored`` without the space runs the translator opened.

    A run the source carries itself is left alone, because an aligned block in a
    code sample means its spacing.

    Args:
        restored: the translation with every protected span put back.
        source: the source message.
    """
    if "  " in source or "\t" in source:
        return restored
    return RUN_OF_SPACES.sub(" ", restored)


def terminate(restored: str, source: str) -> str:
    """Return ``restored`` with the sentence end the translator lost.

    A closing bracket that moves in front of a protected span takes the full
    stop behind it with it, which leaves the sentence running on.

    Args:
        restored: the translation with every protected span put back.
        source: the source message.
    """
    end = source.rstrip()[-1:]
    if end not in TERMINATORS or restored.rstrip().endswith(tuple(TERMINATORS)):
        return restored
    return restored.rstrip() + end


def recapitalise(restored: str, source: str) -> str:
    """Return ``restored`` with the capital its opening word lost.

    Args:
        restored: the translation with every protected span put back.
        source: the source message.
    """
    if not source[:1].isupper() or not restored[:1].islower():
        return restored
    return restored[0].upper() + restored[1:]


TOKEN = re.compile(r'<x id="(\d+)"\s*/?>(?:\s*</x>)?')


@dataclass(frozen=True)
class Masked:
    """A message prepared for an HTML-mode translation request.

    Args:
        text: HTML with every protected span replaced by an ``<x>`` token.
        spans: the protected spans, indexed by token id.
    """

    text: str
    spans: tuple[str, ...]


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


def harms(source: str, translation: str, language: str = "") -> bool:
    """Return whether ``translation`` broke something ``source`` carried.

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
        return sum(character.isalpha() for character in prose(source)) >= ECHO_FLOOR
    return bool(
        protected_spans(translation) != protected_spans(source)
        or missing_names(source, translation)
        or stutters(source, translation)
        or untranslated(translation, language)
        or truncated(source, translation)
        or structure(translation) != structure(source)
        or tighten(translation) != translation
        or resegment(translation, mask(source).spans, source) != translation
    )


def prose(text: str) -> str:
    """Return ``text`` with every protected span removed.

    Args:
        text: a source message.
    """
    plain, position = [], 0
    for start, end in matches(text):
        plain.append(text[position:start])
        position = end
    plain.append(text[position:])
    return "".join(plain)


def has_words(text: str) -> bool:
    """Return whether ``text`` holds any letter outside its protected spans.

    Args:
        text: a source message.
    """
    return any(character.isalpha() for character in prose(text))


def mask(text: str) -> Masked:
    """Return ``text`` escaped for HTML with its protected spans tokenised.

    Args:
        text: the source message.
    """
    spans: list[str] = []
    parts: list[str] = []
    position = 0
    for start, end in matches(text):
        parts.append(html.escape(text[position:start], quote=False))
        parts.append(f'<x id="{len(spans)}"></x>')
        spans.append(text[start:end])
        position = end
    parts.append(html.escape(text[position:], quote=False))
    return Masked("".join(parts), tuple(spans))


def unmask(
    translated: str, masked: Masked, source: str, language: str = ""
) -> str | None:
    """Return the plain translation, or ``None`` when it damaged a protected span.

    Args:
        translated: the HTML the translator returned for ``masked``.
        masked: the request built by ``mask``.
        source: the source message.
        language: ISO 639-1 code of the catalog being filled.
    """
    seen: list[int] = []
    pieces: list[str] = []
    position = 0
    for match in TOKEN.finditer(translated):
        index = int(match.group(1))
        if index >= len(masked.spans):
            return None
        pieces.append(html.unescape(translated[position : match.start()]))
        pieces.append(masked.spans[index])
        seen.append(index)
        position = match.end()
    pieces.append(html.unescape(translated[position:]))
    restored = resegment(tighten("".join(pieces).strip()), masked.spans, source)
    restored = recapitalise(terminate(collapse(restored, source), source), source)
    if sorted(seen) != list(range(len(masked.spans))):
        return None
    if not restored or harms(source, restored, language):
        return None
    return restored
