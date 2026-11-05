"""Attribution recorded in markdown ``## Credits`` sections.

A role's author is declared in ``galaxy_info.author`` and rendered without a
link, so nothing here feeds the README generator any more. What remains
backs the ``credits-attribution`` lint: it reads the linked mentions already
present in prose and holds them to one link per person.

Patterns exported here:

* ``LINKED_RE``     ``[Name](https://url)`` plus the bold markers a Credits
                    line wraps it in.
* ``BARE_BOLD_RE``  ``**Name**`` that is not itself a link's text.
* ``PERSON_RE``     a multi-word proper name whose parts carry no dot. The
                    dot is what separates people from the products and
                    projects that also appear in Credits lines
                    ("Infinito.Nexus Project"). A person written with an
                    initial ("J. Smith") therefore falls out of enforcement
                    rather than into a false positive, which is the safe
                    direction for a lint.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.cache.files import iter_non_ignored_files, read_text

if TYPE_CHECKING:
    from collections.abc import Iterator

CREDITS_HEADING_RE = re.compile(r"^##+\s+Credits\s*$", re.IGNORECASE)
ANY_HEADING_RE = re.compile(r"^##+\s+")

LINKED_RE = re.compile(r"\*{0,2}\[([^\]\[]+)\]\((https?://[^)\s]+)\)\*{0,2}")

BARE_BOLD_RE = re.compile(r"(?<!\])\*\*([^*\]]+)\*\*(?!\()")

PERSON_RE = re.compile(r"^[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)+$")


def is_person(name: str) -> bool:
    return bool(PERSON_RE.match(name.strip()))


def credits_lines(lines: list[str]) -> list[tuple[int, str]]:
    """``(1-based line number, text)`` for every line inside a ``## Credits``
    section, ending at the next heading of any level.

    Args:
        lines: the file's lines, without trailing newlines.
    """
    out: list[tuple[int, str]] = []
    inside = False
    for idx, raw in enumerate(lines, start=1):
        if CREDITS_HEADING_RE.match(raw):
            inside = True
            continue
        if inside and ANY_HEADING_RE.match(raw):
            inside = False
            continue
        if inside:
            out.append((idx, raw))
    return out


def collect_author_urls(documents: list[list[str]]) -> dict[str, set[str]]:
    """Map every credited person to the set of URLs they are linked with.

    A name with more than one URL is a conflict the caller decides about;
    this function reports rather than resolves it.

    Args:
        documents: one entry per file, each the file's lines.
    """
    urls: dict[str, set[str]] = {}
    for lines in documents:
        for _line_no, text in credits_lines(lines):
            for name, url in LINKED_RE.findall(text):
                if is_person(name):
                    urls.setdefault(name.strip(), set()).add(url)
    return urls


def iter_markdown_documents() -> Iterator[tuple[str, list[str]]]:
    """Yield ``(path, lines)`` for every tracked markdown file.

    Files the process cannot read are skipped rather than raised: this walk
    backs the README build, and an unreadable agent scratch file such as
    ``.claude/loop.md`` must not abort generating documentation.
    """
    for path in iter_non_ignored_files(extensions=(".md",)):
        try:
            yield path, read_text(path).splitlines()
        except OSError:
            continue
