"""Lint: the generated README sections are emitted by the template, never committed.

``MANAGED_SECTIONS`` in :mod:`cli.build.docs.readme.generate` is the single
source of truth for the sections the documentation build owns. This lint holds
both directions of that ownership:

* A committed ``roles/*/README.md`` must not contain one, at any heading level.
  A committed copy is a snapshot that goes stale while reading as
  authoritative, and it is what arrives when a branch written before a section
  moved into the generator is merged.
* The template must still emit every one of them. That direction has teeth:
  :func:`cli.build.docs.readme.generate._managed_blocks` builds its dict from
  the rendered template, so a section dropped from the template silently
  disappears from the dict, and the generator then *removes* that section from
  every role README it rewrites. Attribution would vanish from several hundred
  files with only a ``remove Credits`` line in the build log.

``tests/lint/ansible/roles/test_readme.py`` enforces the committed direction
for H2 headings as part of its wider conformance check; this lint covers the
other heading levels and owns the template direction.

Per-line opt-out: ``<!-- nocheck: managed-section-committed -->``.
"""

from __future__ import annotations

import re
import unittest

from cli.build.docs.readme import schema
from cli.build.docs.readme.generate import MANAGED_SECTIONS
from cli.build.docs.readme.sections import h2_titles
from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, read_text

_RULE = "managed-section-committed"
_ROLES_DIR = PROJECT_ROOT / "roles"
_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")


def managed_headings(content: str) -> list[tuple[int, str]]:
    """Return ``(line number, heading)`` for every managed section heading.

    Matching is case-insensitive and covers every heading level, because the
    generator owns the section regardless of the level someone wrote it at.

    Args:
        content: markdown file content.
    """
    wanted = {title.casefold() for title in MANAGED_SECTIONS}
    found: list[tuple[int, str]] = []
    for idx, line in enumerate(content.splitlines()):
        match = _HEADING.match(line.strip())
        if match and match.group("title").casefold() in wanted:
            found.append((idx + 1, line.strip()))
    return found


class TestManagedSectionsNotCommitted(unittest.TestCase):
    def test_no_role_readme_commits_a_managed_section(self) -> None:
        findings: list[tuple[str, int, str]] = []
        scanned = 0
        for readme in sorted(_ROLES_DIR.glob("*/README.md")):
            scanned += 1
            content = read_text(str(readme))
            lines = content.splitlines()
            rel = readme.relative_to(PROJECT_ROOT).as_posix()
            for line_no, heading in managed_headings(content):
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, line_no, heading))

        self.assertGreater(
            scanned, 0, "no role README was scanned, so the rule passes vacuously"
        )

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {h}"
                for p, n, h in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found sections the documentation build owns committed into "
                "role READMEs. A committed copy goes stale while reading as "
                f"authoritative.\n\nOwned sections: {', '.join(MANAGED_SECTIONS)}"
                "\n\nFix: delete the section; the build re-emits it from role "
                f"metadata.\n\nOffending headings:\n{formatted}"
            )

    def test_the_template_emits_every_managed_section(self) -> None:
        emitted = set(h2_titles(schema.render_full()))
        missing = sorted(set(MANAGED_SECTIONS) - emitted)
        self.assertEqual(
            [],
            missing,
            "templates/roles/README.md.j2.tmpl must emit every section the "
            "generator manages. A section missing here is absent from "
            "_managed_blocks, and the generator then deletes it from every "
            f"role README it rewrites; missing: {missing}",
        )

    def test_the_scan_recognises_every_owned_section(self) -> None:
        for title in MANAGED_SECTIONS:
            for level in ("##", "#", "####"):
                with self.subTest(title=title, level=level):
                    self.assertEqual(1, len(managed_headings(f"{level} {title}")))
            with self.subTest(title=title, case="lowered"):
                self.assertEqual(1, len(managed_headings(f"## {title.lower()}")))

        ignored = (
            "## Features",
            "## Credits and Licensing",
            f"- [{MANAGED_SECTIONS[0]}](../../README.md)",
            f"The {MANAGED_SECTIONS[0]} section is generated.",
        )
        for line in ignored:
            with self.subTest(ignored=line):
                self.assertEqual([], managed_headings(line))
