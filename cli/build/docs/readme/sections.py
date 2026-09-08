"""Split a Markdown README into its H2 sections (fence-aware)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_H2_RE = re.compile(r"^##\s+(.*?)\s*$")
_FENCE_RE = re.compile(r"^\s*`{3,}")


@dataclass
class Readme:
    """A parsed README: everything before the first H2, then its H2 blocks."""

    preamble: str
    sections: list[tuple[str, str]]

    def titles(self) -> list[str]:
        return [title for title, _ in self.sections]

    def render(self) -> str:
        parts = [self.preamble.rstrip("\n")] if self.preamble.strip() else []
        parts.extend(block.rstrip("\n") for _, block in self.sections)
        return "\n\n".join(parts) + "\n"


def _h2_starts(lines: list[str]) -> list[int]:
    """Line indexes of every H2 heading outside a fenced code block."""
    starts: list[int] = []
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence and _H2_RE.match(line):
            starts.append(i)
    return starts


def parse_readme(text: str) -> Readme:
    lines = text.splitlines()
    starts = _h2_starts(lines)
    if not starts:
        return Readme(preamble=text, sections=[])

    preamble = "\n".join(lines[: starts[0]])
    sections: list[tuple[str, str]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        title = _H2_RE.match(lines[start]).group(1)
        block = "\n".join(lines[start:end]).rstrip("\n")
        sections.append((title, block))
    return Readme(preamble=preamble, sections=sections)


def h2_titles(text: str) -> list[str]:
    """Return the ordered H2 titles of a Markdown document (fence-aware)."""
    return parse_readme(text).titles()
