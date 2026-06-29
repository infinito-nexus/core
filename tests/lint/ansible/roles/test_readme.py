"""Lint guard: every ``roles/<role>/README.md`` MUST conform to the
role README convention defined in
``docs/contributing/artefact/files/role/readme_md.md``.

Enforced (hard fail) rules
==========================

1. **No emojis in any heading.** Galaxy / dashboard tooling parses heading
   text; emojis break the parser. The convention forbids emojis in role
   README headings at every level.
2. **Required H2 sections present.** Every role README MUST carry the four
   mandatory sections ``## Description``, ``## Overview``, ``## Features``
   and ``## Credits``.
3. **Section order.** Required H2s MUST appear in the convention order
   Description → Overview → Features → … → Credits, and ``## Credits``
   MUST be the last H2 heading in the file.
4. **Canonical Credits block.** The Credits paragraph MUST match the
   project's fixed wording byte-for-byte (Kevin Veen-Birkenbach /
   Consulting & Coaching Solutions / Infinito.Nexus Project / Community
   License). The same exact-value is enforced for ``galaxy_info.company``
   in :mod:`tests.lint.ansible.roles.meta.test_main_galaxy_schema` so
   the role's metadata and its README stay in sync.

Soft / fuzzy rules from ``readme_md.md`` (sentence-case headings,
"H1 must be the human-readable software name", "Description must link the
software to its official website on first use", "every Feature item starts
with a bold label and a colon") are deliberately NOT enforced here — they
need human judgement and would produce false positives.

Files outside ``roles/<role>/README.md`` (for example
``roles/<role>/files/README.md``) are out of scope. Presence of the
top-level role README is enforced separately by
``tests/integration/roles/applications/test_web_app_readme.py``.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT, read_text

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)
_EMOJI_RE = re.compile(
    "[\U00002600-\U000027bf\U0001f000-\U0001f2ff\U0001f300-\U0001faff]"
)

_REQUIRED_H2_ORDER: tuple[str, ...] = ("Description", "Overview", "Features")
_CREDITS_HEADING: str = "Credits"

_CANONICAL_CREDITS: str = (
    "## Credits\n"
    "\n"
    "Developed and maintained by **Kevin Veen-Birkenbach**.\n"
    "Learn more at [veen.world](https://www.veen.world).\n"
    "Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).\n"
    "Licensed under the [Infinito.Nexus Community License (Non-Commercial)]"
    "(https://s.infinito.nexus/license).\n"
)


def _role_readmes() -> list[Path]:
    if not ROLES_DIR.is_dir():
        return []
    return sorted(
        role_dir / "README.md"
        for role_dir in ROLES_DIR.iterdir()
        if role_dir.is_dir() and (role_dir / "README.md").is_file()
    )


def _parse_headings(text: str) -> list[tuple[int, int, str]]:
    """Return [(line_no, level, title)] for every heading in `text`."""
    out: list[tuple[int, int, str]] = []
    for ln, line in enumerate(text.splitlines(), 1):
        m = _HEADING_RE.match(line)
        if m:
            out.append((ln, len(m.group(1)), m.group(2).strip()))
    return out


def _validate_readme(path: Path) -> list[str]:
    """Return human-readable problems for one role README."""
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError) as exc:
        return [f"read error: {exc}"]

    problems: list[str] = []
    headings = _parse_headings(text)

    for ln, _level, title in headings:
        if _EMOJI_RE.search(title):
            problems.append(f"L{ln}: heading contains emoji: {title!r}")

    h2_titles = [t for _, lvl, t in headings if lvl == 2]
    h2_set = set(h2_titles)
    problems.extend(
        f"missing required H2 section '{required}'"
        for required in (*_REQUIRED_H2_ORDER, _CREDITS_HEADING)
        if required not in h2_set
    )

    last_pos = -1
    for required in _REQUIRED_H2_ORDER:
        if required in h2_titles:
            pos = h2_titles.index(required)
            if pos < last_pos:
                problems.append(
                    f"section '{required}' appears out of order; expected "
                    f"order: {' → '.join(_REQUIRED_H2_ORDER)} → … → "
                    f"{_CREDITS_HEADING}"
                )
            last_pos = pos

    if h2_titles and h2_titles[-1] != _CREDITS_HEADING:
        problems.append(
            f"last H2 is '{h2_titles[-1]}', not '{_CREDITS_HEADING}'; "
            f"Credits MUST be the last H2 section"
        )

    if _CANONICAL_CREDITS not in text:
        problems.append(
            "Credits block does not match the canonical wording "
            "(see docs/contributing/artefact/files/role/readme_md.md)"
        )

    return problems


class TestRoleReadme(unittest.TestCase):
    """Every role README MUST conform to the readme_md.md role convention."""

    def test_role_readmes_are_conformant(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _role_readmes():
            problems = _validate_readme(path)
            if problems:
                offenders[path] = problems

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [
            f"{len(offenders)} role README.md file(s) violate "
            f"docs/contributing/artefact/files/role/readme_md.md:"
        ]
        for path, problems in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            lines.extend(f"      * {problem}" for problem in problems)
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
