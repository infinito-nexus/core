"""Forbid writing the software's repository URL instead of ``SOFTWARE_REPOSITORY``.

``group_vars/all/00_general.yml`` declares ``SOFTWARE_REPOSITORY`` and is the
only file that spells the URL. Ansible reads the group var, Python imports
``utils.software.SOFTWARE_REPOSITORY``, and the role README template receives it
as ``software_repository``.

Scope: every non-ignored file, tests included, except the declaring file,
``.md`` documentation and its ``.po`` translations.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.cache.files import iter_non_ignored_files, read_text
from utils.software import SOFTWARE_REPOSITORY, SOFTWARE_VARS

from . import PROJECT_ROOT


def _findings() -> list[str]:
    spot = SOFTWARE_VARS.relative_to(PROJECT_ROOT).as_posix()
    found = []
    for path_str in iter_non_ignored_files():
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if rel == spot or rel.endswith((".md", ".po")):
            continue
        try:
            content = read_text(path_str)
        except (OSError, UnicodeDecodeError):
            continue
        found.extend(
            f"- {rel}:{number}"
            for number, line in enumerate(content.splitlines(), start=1)
            if SOFTWARE_REPOSITORY in line
        )
    return found


class TestSoftwareRepositorySpot(unittest.TestCase):
    def test_only_its_declaration_spells_the_repository_url(self) -> None:
        findings = _findings()
        self.assertEqual(
            findings,
            [],
            "The repository URL is written out instead of read from "
            "SOFTWARE_REPOSITORY. Use the group var in Ansible, "
            "utils.software.SOFTWARE_REPOSITORY in Python and "
            "{{ software_repository }} in the role README template:\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
