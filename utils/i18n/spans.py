"""Which parts of a message are protected, and how they are masked for a request.

The base layer of :mod:`utils.i18n.placeholders`: it knows the protection rules
and nothing about damage or repair, so :mod:`utils.i18n.damage` can build on it
without an import cycle.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from functools import lru_cache

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

EXTRA = re.compile(
    r"[\U0001F300-\U0001FAFF☀-➿️]"
    r"|[\w.+-]+@[\w-]+\.[\w.]+"
)

TOKEN = re.compile(r'<x id="(\d+)"\s*/?>(?:\s*</x>)?')


def carries_placeholder(message_id: str | tuple[str, ...]) -> bool:
    """Return whether ``message_id`` holds a printf placeholder a translation must keep.

    Args:
        message_id: a catalog message id, singular or a plural tuple.
    """
    forms = message_id if isinstance(message_id, tuple) else (message_id,)
    return any(PLACEHOLDER.search(form) for form in forms)


@lru_cache(maxsize=1 << 17)
def _claimed(text: str, with_names: bool) -> tuple[tuple[int, int], ...]:
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
    return tuple(kept)


def matches(text: str, with_names: bool = True) -> list[tuple[int, int]]:
    """Return the non-overlapping offsets every protection rule claims.

    The scan is cached behind a fresh list, because one source message is
    scanned once per target language and callers may sort or trim the result.

    Args:
        text: a source message or its translation.
        with_names: whether role names and titles take part. They do when a
            request is masked, so the translator never sees them, and they do
            not when two texts are compared: German capitalises every noun, so
            the lowercase ``shell extensions`` becomes ``Shell-Erweiterungen``
            and a set comparison would read the capital as a surplus span.
    """
    return list(_claimed(text, with_names))


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


@dataclass(frozen=True)
class Masked:
    """A message prepared for an HTML-mode translation request.

    Args:
        text: HTML with every protected span replaced by an ``<x>`` token.
        spans: the protected spans, indexed by token id.
    """

    text: str
    spans: tuple[str, ...]


@lru_cache(maxsize=1 << 16)
def mask(text: str) -> Masked:
    """Return ``text`` escaped for HTML with its protected spans tokenised.

    The result is immutable and one source message is masked once per target
    language, so the same string arrives dozens of times per run.

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
