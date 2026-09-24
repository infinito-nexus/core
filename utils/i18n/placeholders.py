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
EMPHASIS = re.compile(r"(\*\*)[ \t]*([^\s]|[^\s].*?[^\s])[ \t]*\1", re.DOTALL)


def resegment(restored: str, spans: tuple[str, ...], source: str) -> str:
    """Put back the sentence boundary a translator dropped behind a protected span.

    Args:
        restored: the translation with every protected span put back.
        spans: the protected spans of the source.
        source: the source message, which holds the boundary that went missing.
    """
    for span in spans:
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


def has_words(text: str) -> bool:
    """Return whether ``text`` holds any letter outside its protected spans.

    Args:
        text: a source message.
    """
    plain, position = [], 0
    for start, end in matches(text):
        plain.append(text[position:start])
        position = end
    plain.append(text[position:])
    return any(character.isalpha() for character in "".join(plain))


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


def unmask(translated: str, masked: Masked, source: str) -> str | None:
    """Return the plain translation, or ``None`` when it damaged a protected span.

    Args:
        translated: the HTML the translator returned for ``masked``.
        masked: the request built by ``mask``.
        source: the source message.
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
    if sorted(seen) != list(range(len(masked.spans))):
        return None
    if not restored or protected_spans(restored) != protected_spans(source):
        return None
    return restored
