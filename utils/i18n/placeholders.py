"""Protection of the parts of a message that machine translation must not touch."""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass

PROTECTED = re.compile(
    r"``.+?``"
    r"|:[\w.+-]+:`[^`]+`"
    r"|`[^`]+`_{0,2}"
    r"|\{[A-Za-z_]\w*\}"
    r"|%\([A-Za-z_]\w*\)[sdif]"
    r"|%[sdif]"
    r"|https?://[^\s<>\"'`)\]]+"
    r"|<[^<>\s]+>"
    r"|\]\([^)\s]+\)"
    r"|(?<![\w/@.-])[\w.-]+/[\w.@+-]+(?:/[\w.@+-]+)+"
    r"|(?<![\w/@.-])[\w.-]+/[\w.@+-]*\.[A-Za-z]\w{0,7}\b"
    r"|\b[A-Za-z]\w*(?:\.[A-Za-z]\w+)+"
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
    return Counter(PROTECTED.findall(text))


def has_words(text: str) -> bool:
    """Return whether ``text`` holds any letter outside its protected spans.

    Args:
        text: a source message.
    """
    return any(character.isalpha() for character in PROTECTED.sub("", text))


def mask(text: str) -> Masked:
    """Return ``text`` escaped for HTML with its protected spans tokenised.

    Args:
        text: the source message.
    """
    spans: list[str] = []
    parts: list[str] = []
    position = 0
    for match in PROTECTED.finditer(text):
        parts.append(html.escape(text[position : match.start()], quote=False))
        parts.append(f'<x id="{len(spans)}"></x>')
        spans.append(match.group(0))
        position = match.end()
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
    restored = "".join(pieces).strip()
    if sorted(seen) != list(range(len(masked.spans))):
        return None
    if not restored or protected_spans(restored) != protected_spans(source):
        return None
    return restored
