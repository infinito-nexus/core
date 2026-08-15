"""Lint inconsistent attribution inside ``## Credits`` sections.

A person credited in one markdown file with a link
(``[Kevin Veen-Birkenbach](https://www.veen.world)``) but in another with a
bare name (``**Kevin Veen-Birkenbach**``) reads as two different people and
drops the reader's path to that person. This lint requires a name linked
anywhere to carry that same link everywhere it is credited.

It also rejects the same name pointing at two different URLs, because then
neither mention can be trusted.

The name -> URL derivation is shared with the README generator
(``utils/roles/credits.py``), so a fix here and the generated output cannot
drift apart.

Only ``## Credits`` sections are scanned: prose elsewhere legitimately names
people without linking them.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``<!-- nocheck: credits-attribution -->`` in the head of a markdown file
  exempts the whole file.
* ``<!-- nocheck: credits-attribution -->`` on (or directly above) the
  offending line exempts that single finding.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import NamedTuple

from utils.annotations.suppress import is_suppressed_at, is_suppressed_in_head
from utils.roles.credits import (
    BARE_BOLD_RE,
    CREDITS_HEADING_RE,
    LINKED_RE,
    collect_author_urls,
    credits_lines,
    iter_markdown_documents,
)

from . import PROJECT_ROOT

_RULE = "credits-attribution"


class Finding(NamedTuple):
    path: str
    line: int
    name: str
    detail: str


class TestCreditsAttribution(unittest.TestCase):
    """A name linked in any Credits section must be linked in all of them."""

    def test_credited_names_carry_their_link_everywhere(self) -> None:
        files: list[tuple[str, list[str]]] = []
        for raw_path, lines in iter_markdown_documents():
            if is_suppressed_in_head(lines, _RULE):
                continue
            if any(CREDITS_HEADING_RE.match(line) for line in lines):
                rel = Path(raw_path).relative_to(PROJECT_ROOT).as_posix()
                files.append((rel, lines))

        urls = collect_author_urls([lines for _rel, lines in files])
        findings: list[Finding] = []

        for name, seen in sorted(urls.items()):
            if len(seen) > 1:
                findings.append(
                    Finding(
                        "<repository>",
                        0,
                        name,
                        f"credited with {len(seen)} different URLs: "
                        f"{', '.join(sorted(seen))}",
                    )
                )

        known = {
            name: next(iter(seen)) for name, seen in urls.items() if len(seen) == 1
        }

        for rel, lines in files:
            for line_no, text in credits_lines(lines):
                linked = {n.strip() for n, _u in LINKED_RE.findall(text)}
                for bare in BARE_BOLD_RE.findall(text):
                    name = bare.strip()
                    if name in linked or name not in known:
                        continue
                    if is_suppressed_at(lines, line_no, _RULE):
                        continue
                    findings.append(
                        Finding(
                            rel,
                            line_no,
                            name,
                            f"credited bare here but linked to {known[name]} "
                            f"elsewhere; use [{name}]({known[name]})",
                        )
                    )

        self.assertFalse(
            findings,
            f"{len(findings)} inconsistent Credits attribution(s) ({_RULE}).\n"
            "A person credited with a link in one place MUST carry that same "
            "link everywhere they are credited, so the reader always reaches "
            "them.\n"
            + "\n".join(
                f"  - {f.path}:{f.line} {f.name}: {f.detail}"
                for f in sorted(findings, key=lambda f: (f.path, f.line))
            ),
        )


if __name__ == "__main__":
    unittest.main()
