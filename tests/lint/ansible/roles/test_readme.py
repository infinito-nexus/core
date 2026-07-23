"""Lint guard: every ``roles/<role>/README.md`` MUST conform to the
role README convention defined in
``docs/contributing/artefact/files/role/readme_md.md``.

Enforced (hard fail) rules
==========================

1. **No emojis in any heading.** Galaxy / dashboard tooling parses heading
   text; emojis break the parser. The convention forbids emojis in role
   README headings at every level.
2. **Required H2 sections present.** The mandatory sections are derived
   from the template ``templates/roles/README.md.j2.tmpl`` (the H2s it emits
   with no optional context): ``## Description``, ``## Overview``,
   ``## Cosmos``, ``## Features`` and ``## Credits``. The template is the
   single source of truth; ``cli.build.readme.schema`` reads it.
3. **Section order.** Those required H2s MUST appear in the template order
   (extra H2s MAY be interleaved between them), and ``## Credits`` MUST be
   the last H2 heading in the file.
4. **Credits block.** The Credits paragraph MUST carry the fixed
   "Implemented by …" / "Part of … maintained by Kevin Veen-Birkenbach" /
   license wording. The implementing author is NOT hard-coded: it is the
   single point of truth ``galaxy_info.author`` read from the role's own
   ``meta/main.yml``. The README author (bold, optionally wrapped in a
   Markdown link) MUST equal that value byte-for-byte, so a role's
   metadata and its README stay in sync.
5. **Cosmos diagram.** Every role README MUST carry a ``## Cosmos`` H2 whose
   body contains a ```mermaid fenced diagram placing the role in the
   Infinito.Nexus cosmos (capabilities / dependencies / cosmos). The
   authoring spec emitted on failure lives in ``_COSMOS_FIX_PROMPT``.
6. **Quick Setup is invokable-gated and template-exact.** Invokable roles
   (per ``categories.yml``) MUST carry a ``## Quick Setup`` section whose body
   equals the generator's render for that role; every other role MUST NOT
   carry it. The template emits it behind ``application_invokable``.

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

import yaml as _yaml

from cli.build.readme import schema
from cli.build.readme.generate import _app_name, _managed_blocks
from cli.build.readme.sections import parse_readme
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MAIN
from utils.roles.validation.invokable import _get_invokable_paths, _is_role_invokable

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)
_EMOJI_RE = re.compile(
    "[\U00002600-\U000027bf\U0001f000-\U0001f2ff\U0001f300-\U0001faff]"
)

_REQUIRED_SECTIONS: tuple[str, ...] = schema.required_sections()
_CREDITS_HEADING: str = schema.credits_heading()
_COSMOS_HEADING: str = "Cosmos"
_QUICK_SETUP_HEADING: str = "Quick Setup"
_MERMAID_FENCE_RE = re.compile(r"^```mermaid\b", re.MULTILINE)

_COSMOS_FIX_PROMPT: str = """\
How to author a conformant '## Cosmos' section
==============================================
Every role README MUST contain exactly one '## Cosmos' H2 whose body includes a
```mermaid fenced diagram. The diagram places the role in the Infinito.Nexus
cosmos and MUST cover three groups, drawn with `subgraph`s:

  1. Capabilities  – the containers/components THIS role deploys
                     (meta/services.yml entries that define image/name).
  2. Dependencies  – the central services + sibling roles it consumes
                     (the `enabled: "{{ '<role>' in group_names }}"` service
                     flags, plus `run_after` and meta/main.yml `dependencies`).
  3. Cosmos        – the outward reach: federation peers, external networks
                     bridged in, upstream projects.

Rules:
  - Heading MUST be exactly '## Cosmos' (NO emoji — heading emojis are a hard fail).
  - Body MUST contain exactly one ```mermaid ... ``` block.
  - Use a `flowchart`; group nodes with `subgraph` (Capabilities / Dependencies / Cosmos).
  - Draw the role as the centre. Dependencies point INTO it; capabilities hang
    off it; cosmos/external sit on outward edges.
  - Diagram ONLY what the role's meta actually declares. Do NOT invent services.
  - Node ids MUST NOT be Mermaid reserved words (`call`, `end`, `click`, `class`,
    `graph`, `style`, `subgraph`); rename e.g. `call` -> `elementcall`.
  - Place the section after '## Features' and before '## Credits'.

To fix an offender: read roles/<role>/meta/services.yml, roles/<role>/meta/main.yml,
and the existing README, then draw the nodes you find."""

_CREDITS_IMPL_RE = re.compile(
    r"Implemented by \*\*"
    r"(?:\[(?P<linked>[^\]]+)\]\([^)]+\)|(?P<plain>[^*\[\]]+))"
    r"\*\*\."
)

_CREDITS_TAIL: str = (
    "Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) "
    "and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).\n"
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


def _cosmos_body(text: str) -> str | None:
    """Return the text between '## Cosmos' and the next H2, or None if absent."""
    lines = text.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) == 2 and m.group(2).strip() == _COSMOS_HEADING:
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        m = _HEADING_RE.match(lines[j])
        if m and len(m.group(1)) == 2:
            end = j
            break
    return "\n".join(lines[start:end])


def _validate_quick_setup(readme_path: Path, role_name: str, text: str) -> list[str]:
    """Quick Setup body MUST equal the template render for this role."""
    parsed = parse_readme(text)
    actual = next(
        (block for title, block in parsed.sections if title == _QUICK_SETUP_HEADING),
        None,
    )
    if actual is None:
        return []
    app_name = _app_name(parsed.preamble, role_name)
    try:
        expected = _managed_blocks(
            readme_path.parent, role_name, app_name, invokable=True
        ).get(_QUICK_SETUP_HEADING)
    except Exception as exc:
        return [f"'## {_QUICK_SETUP_HEADING}' template render failed: {exc}"]
    if expected is not None and actual.strip() != expected.strip():
        return [
            f"'## {_QUICK_SETUP_HEADING}' drifted from the template; "
            f"regenerate with: make readme-generate role={role_name} quick_setup=true"
        ]
    return []


def _role_author(readme_path: Path) -> str | None:
    """Return `galaxy_info.author` from the role's meta/main.yml, or None."""
    meta_path = readme_path.parent / ROLE_FILE_META_MAIN
    try:
        parsed = load_yaml_any(str(meta_path), default_if_missing={})
    except (OSError, _yaml.YAMLError):
        return None
    galaxy_info = parsed.get("galaxy_info") if isinstance(parsed, dict) else None
    author = galaxy_info.get("author") if isinstance(galaxy_info, dict) else None
    return author if isinstance(author, str) and author.strip() else None


def _validate_credits(text: str, path: Path) -> list[str]:
    """Return problems with the Credits block for one README."""
    problems: list[str] = []
    author = _role_author(path)
    if author is None:
        problems.append(
            "cannot read galaxy_info.author from sibling meta/main.yml "
            "(required to validate the Credits author)"
        )

    match = _CREDITS_IMPL_RE.search(text)
    if match is None:
        problems.append(
            "Credits must contain 'Implemented by **<author>**.' "
            "(the author name MAY be wrapped in a Markdown link)"
        )
    elif author is not None:
        found = match.group("linked") or match.group("plain")
        if found != author:
            problems.append(
                f"Credits author {found!r} does not match galaxy_info.author "
                f"{author!r} in meta/main.yml (the author SPOT)"
            )

    if _CREDITS_TAIL not in text:
        problems.append(
            "Credits tail does not match the canonical wording "
            "(see docs/contributing/artefact/files/role/readme_md.md)"
        )
    return problems


def _validate_readme(path: Path, invokable_paths: list[str]) -> list[str]:
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
        for required in _REQUIRED_SECTIONS
        if required not in h2_set
    )

    present_required = [t for t in h2_titles if t in set(_REQUIRED_SECTIONS)]
    expected_order = [r for r in _REQUIRED_SECTIONS if r in h2_set]
    if present_required != expected_order:
        problems.append(
            "required sections out of order; they MUST appear in the template "
            f"order: {' → '.join(_REQUIRED_SECTIONS)} "
            "(extra sections MAY be interleaved between them)"
        )

    if h2_titles and h2_titles[-1] != _CREDITS_HEADING:
        problems.append(
            f"last H2 is '{h2_titles[-1]}', not '{_CREDITS_HEADING}'; "
            f"Credits MUST be the last H2 section"
        )

    body = _cosmos_body(text)
    if body is not None and not _MERMAID_FENCE_RE.search(body):
        problems.append("'## Cosmos' section contains no ```mermaid diagram")

    has_quick_setup = _QUICK_SETUP_HEADING in h2_set
    if _is_role_invokable(path.parent.name, invokable_paths):
        if not has_quick_setup:
            problems.append(
                f"invokable role MUST have a '## {_QUICK_SETUP_HEADING}' section"
            )
        else:
            problems.extend(_validate_quick_setup(path, path.parent.name, text))
    elif has_quick_setup:
        problems.append(
            f"non-invokable role MUST NOT have a '## {_QUICK_SETUP_HEADING}' section"
        )

    problems.extend(_validate_credits(text, path))

    return problems


class TestRoleReadme(unittest.TestCase):
    """Every role README MUST conform to the readme_md.md role convention."""

    def test_role_readmes_are_conformant(self) -> None:
        invokable_paths = _get_invokable_paths()
        offenders: dict[Path, list[str]] = {}
        for path in _role_readmes():
            problems = _validate_readme(path, invokable_paths)
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

        if any(
            _COSMOS_HEADING in problem
            for problems in offenders.values()
            for problem in problems
        ):
            lines.append("")
            lines.append(_COSMOS_FIX_PROMPT)

        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
