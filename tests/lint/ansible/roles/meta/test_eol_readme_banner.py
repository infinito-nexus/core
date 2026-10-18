"""Lint guard: a role tagged ``lifecycle: eol`` carries the README banner.

``docs/contributing/design/role/services/lifecycle.md`` makes the banner a MUST
for the ``eol`` stage: the README has to state that the project neither
maintains nor tests the role and that an operator runs it at their own risk.
Nothing enforced it, so all four EOL roles shipped without one - the flag flip
and the banner are two separate edits, and only the flag has a lint behind it.

Three things are mechanical, and they are exactly the three the policy calls a
MUST:

* position: the banner starts on the FIRST non-blank line after the H1.
  Searching the whole file instead would pass a banner buried at the bottom
  while the failure message demands it under the title, which is the gap this
  placement closes - an operator who reads the first screen of a README is the
  reader the banner exists for.
* opening: that line starts with ``> **End of life.**``, so one blockquote
  shape covers every role. The ``>`` may or may not be followed by a space.
* clauses: the blockquote states ``neither maintains nor tests`` and ``at your
  own risk``, the two claims the policy spells out. The clauses are matched over
  the whole contiguous ``>`` run, not over one physical line: a Markdown
  blockquote renders as one paragraph however it is wrapped, so judging the
  first line alone rejects a conforming banner with a message denying a clause
  the README does carry.

The vendor link the stage SHOULD carry is not mechanical and is not checked;
a link to nowhere useful is a review question, not a regex.

No suppression marker exists. The stage's own criteria carry no exception: a
role whose README stays silent about its end of life is a role an operator
adopts believing the project stands behind it. Demote the ``lifecycle`` value
instead when the banner does not apply.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.roles.meta_lookup import get_role_lifecycle

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
_EOL = "eol"
_README = "README.md"
_PREFIX = "> **End of life.**"
_PREFIX_RE = re.compile(r"^>\s?\*\*End of life\.\*\*")
_H1_RE = re.compile(r"^#\s+\S")
_CLAUSES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("`neither maintains nor tests`", re.compile(r"neither maintains nor tests\b")),
    ("`at your own risk`", re.compile(r"at your own risk\b")),
)


def _quote_run(lines: list[str], first: int) -> list[str]:
    """The contiguous blockquote lines starting at 0-based *first*.

    Args:
        lines: the README's lines.
        first: the index the run has to start on.

    Returns:
        The run's lines with their leading indentation stripped, so the ``>``
        marker is the first character of the first line, or ``[]`` when *first*
        is not a blockquote line. Lines after the first need no ``>``: Markdown
        renders a lazy continuation as part of the same blockquote, so refusing
        one would reject a conforming banner that merely wraps. Four or more
        leading spaces make it a code block, not a quote.
    """
    if len(lines[first]) - len(lines[first].lstrip(" ")) >= 4:
        return []
    run: list[str] = []
    for raw in lines[first:]:
        stripped = raw.lstrip()
        if not stripped:
            break
        if not stripped.startswith(">") and not run:
            break
        run.append(stripped)
    return run


def banner_offence(text: str) -> str | None:
    """Why *text* fails the banner contract.

    Args:
        text: the README's full contents.

    Returns:
        The clause of the offence, or ``None`` when the banner holds.
    """
    lines = text.splitlines()
    h1 = next((idx for idx, raw in enumerate(lines) if _H1_RE.match(raw)), None)
    if h1 is None:
        return "carries no H1 for the banner to sit under"
    first = next((idx for idx in range(h1 + 1, len(lines)) if lines[idx].strip()), None)
    if first is None:
        return "ends after its H1, so it carries no end-of-life banner"
    run = _quote_run(lines, first)
    if not run or not _PREFIX_RE.match(run[0]):
        return (
            f"line {first + 1} is the first line under the H1 and does not open "
            f"the end-of-life banner with '{_PREFIX}'"
        )
    banner = " ".join(line.lstrip(">").strip() for line in run)
    missing = [name for name, pattern in _CLAUSES if not pattern.search(banner)]
    if missing:
        return (
            f"the banner opening on line {first + 1} states no "
            f"{' and no '.join(missing)} clause"
        )
    return None


class TestEolReadmeBanner(unittest.TestCase):
    def test_every_eol_role_readme_carries_the_banner(self) -> None:
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            if get_role_lifecycle(role_dir) != _EOL:
                continue
            readme = role_dir / _README
            if not readme.is_file():
                offenders.append(f"{role_dir.name}: no {_README}")
                continue
            offence = banner_offence(read_text(str(readme)))
            if offence:
                offenders.append(
                    f"{role_dir.name}: {readme.relative_to(PROJECT_ROOT)} {offence}"
                )

        self.assertEqual(
            offenders,
            [],
            "Every role whose primary entity declares `lifecycle: eol` MUST "
            "open its README with the banner, so an operator reading the role "
            "learns it is unmaintained and untested before deploying it. The "
            "banner is the first line under the H1:\n"
            "  > **End of life.** Infinito.Nexus neither maintains nor tests "
            "this role, and the default `INFINITO_LIFECYCLES` envelope keeps it "
            "out of every CI round. Deploy it at your own risk and take support "
            "from [<vendor>](<url>).\n"
            "Offenders:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
