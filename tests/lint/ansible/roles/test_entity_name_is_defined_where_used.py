"""Lint: a role that uses ``entity_name`` has to define it itself.

Role vars do not cross role boundaries, so a role reading ``entity_name``
without a ``vars/main.yml`` entry reads nothing. Ansible does not stop there:
in compose the undefined value renders into task names as
``<< error 1 - 'entity_name' is undefined >>`` and the play carries on, so the
gap stays invisible until the swarm path templates it into a real argument and
``any_errors_fatal`` takes the whole play down.

Five roles shipped that way while seventy-seven define it on the line below
``application_id``, which is why nothing looked odd in review.

The match needs its lookbehind: ``get_entity_name`` is a filter whose name ends
in this variable's, and without it every role calling that filter reads as a
violation.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: entity-name-undefined`` on, or directly above, the use.
"""

from __future__ import annotations

import os
import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_RULE = "entity-name-undefined"
_NAME = "entity_name"
_ROLES = str(PROJECT_ROOT / "roles") + os.sep

_USE_RE = re.compile(rf"(?<![\w.]){_NAME}\b")


def files_by_role() -> dict:
    """Return every role's yml and j2 files, keyed by role name."""
    grouped: dict = {}
    for path in iter_project_files(extensions=(".yml", ".j2"), exclude_tests=True):
        if not path.startswith(_ROLES):
            continue
        relative = path[len(_ROLES) :]
        grouped.setdefault(relative.split(os.sep)[0], []).append(path)
    return grouped


def defines_it(role: str, paths: list) -> bool:
    """Return whether the role declares the variable in its own vars.

    Args:
        role: the role's directory name.
        paths: the role's files.
    """
    wanted = _ROLES + role + os.sep + ROLE_FILE_VARS_MAIN
    return any(
        line.strip().startswith(f"{_NAME}:")
        for path in paths
        if path == wanted
        for line in read_text(path).splitlines()
    )


def borrowed_files(grouped: dict) -> set:
    """Return every role file another role pulls in by absolute path.

    Args:
        grouped: the roles' files, keyed by role name.

    Such a file runs in the including role's scope, so it reads that role's
    ``entity_name`` and must not be judged against its own role's vars.
    """
    borrowed = set()
    for owner, paths in grouped.items():
        for path in paths:
            for line in read_text(path).splitlines():
                if "path_absolute" not in line or "roles/" not in line:
                    continue
                target = line.split("roles/", 1)[1].split("'")[0].split('"')[0]
                if target.split("/")[0] != owner:
                    borrowed.add(target)
    return borrowed


def uses_it(role: str, paths: list, borrowed: set) -> list:
    """Return one ``path:line`` per unsuppressed use outside the role's vars.

    Args:
        role: the role's directory name.
        paths: the role's files.
        borrowed: role-relative paths other roles include by absolute path.
    """
    uses = []
    for path in sorted(paths):
        relative = path[len(_ROLES) :]
        if relative in borrowed or relative == role + os.sep + ROLE_FILE_VARS_MAIN:
            continue
        lines = read_text(path).splitlines()
        uses.extend(
            f"{relative}:{index}"
            for index, line in enumerate(lines, start=1)
            if _USE_RE.search(line) and not is_suppressed_at(lines, index, _RULE)
        )
    return uses


def roles_using_it_without_defining_it() -> list[str]:
    """Return one finding per role that reads the variable it never sets."""
    grouped = files_by_role()
    borrowed = borrowed_files(grouped)
    findings = []
    for role, paths in sorted(grouped.items()):
        if defines_it(role, paths):
            continue
        findings.extend(
            f"roles/{use}: uses {_NAME}, which {role} never defines"
            for use in uses_it(role, paths, borrowed)
        )
    return findings


class TestEntityNameIsDefinedWhereUsed(unittest.TestCase):
    def test_no_role_reads_an_entity_name_it_never_sets(self) -> None:
        findings = roles_using_it_without_defining_it()
        self.assertEqual(
            [],
            findings,
            f"role(s) reading an undefined {_NAME} ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_reaches_the_roles(self) -> None:
        self.assertTrue(files_by_role(), "no role file was scanned")

    def test_the_convention_it_guards_is_actually_in_use(self) -> None:
        """Without one, an emptied convention would let the rule pass silently."""
        grouped = files_by_role()
        definers = [role for role, paths in grouped.items() if defines_it(role, paths)]
        self.assertGreater(len(definers), 50, "the convention this rule guards is gone")


if __name__ == "__main__":
    unittest.main()
