"""Integration guard: every repository secret and variable a workflow reads is documented.

Background
==========
A `${{ secrets.X }}` or `${{ vars.X }}` reference is a contract with whoever
administers the repository, and an unset one resolves to the empty string
rather than to an error. An undocumented name is therefore invisible twice: the
administrator cannot know to set it, and the run that needed it degrades
silently.

The guard also catches the inverse drift, a doc naming a variable the workflows
no longer read under that name, because it compares the reference against the
page rather than the page against itself.

Scope
=====
Every `${{ secrets.<NAME> }}` and `${{ vars.<NAME> }}` on a non-comment line of
`.github/workflows/*.yml`. Secrets MUST appear in `secrets.md`, variables in
`configuration.md`, both under `docs/contributing/tools/github/actions/`.

Exemptions
==========
`GITHUB_TOKEN` is minted by GitHub for every run; it is not administered and
cannot be set. Any other exemption belongs in `_PROVIDED_SECRETS` with the
reason it is not administrator-supplied.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
DOCS = PROJECT_ROOT / "docs" / "contributing" / "tools" / "github" / "actions"

_REFERENCE = re.compile(r"\$\{\{\s*(secrets|vars)\.([A-Za-z_][A-Za-z0-9_]*)")

_PROVIDED_SECRETS = frozenset({"GITHUB_TOKEN"})

_PAGES = {"secrets": "secrets.md", "vars": "configuration.md"}


def _referenced() -> dict[str, set[str]]:
    """Names the workflows actually read, keyed by `secrets` / `vars`.

    A commented-out line is skipped: it documents an option nobody has taken,
    and demanding a doc row for it would describe an input the run never asks
    for.
    """
    found: dict[str, set[str]] = {"secrets": set(), "vars": set()}
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for line in read_text(str(workflow)).splitlines():
            if line.lstrip().startswith("#"):
                continue
            for kind, name in _REFERENCE.findall(line):
                if kind == "secrets" and name in _PROVIDED_SECRETS:
                    continue
                found[kind].add(name)
    return found


class TestCiInputsDocumented(unittest.TestCase):
    def test_every_referenced_secret_and_variable_is_documented(self) -> None:
        offenders: list[str] = []
        for kind, names in _referenced().items():
            documented = read_text(str(DOCS / _PAGES[kind]))
            offenders.extend(
                f"{kind}.{name} is read by a workflow but absent from "
                f"docs/contributing/tools/github/actions/{_PAGES[kind]}"
                for name in sorted(names)
                if name not in documented
            )

        if offenders:
            self.fail(
                f"{len(offenders)} CI input(s) undocumented:\n"
                + "\n".join(f"- {o}" for o in offenders)
                + "\n\nAn unset secret or variable resolves to the empty string, "
                "so an undocumented one degrades a run instead of failing it. "
                "Add a row naming the workflow, what it enables, and what "
                "happens while it is unset."
            )

    def test_the_guard_reads_workflows_that_exist(self) -> None:
        self.assertTrue(
            any(WORKFLOWS.glob("*.yml")),
            f"no workflow files under {WORKFLOWS}; the guard would pass vacuously",
        )


if __name__ == "__main__":
    unittest.main()
