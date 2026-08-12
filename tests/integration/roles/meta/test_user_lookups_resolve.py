"""Every ``lookup('users', 'mcp-…')`` addresses a service account a role declares.

A role that reads its MCP service account out of the user registry names it by
a literal key. Nothing validates that key: a typo yields an empty password at
deploy time, deep inside a provisioning task, on the one variant that enables
the surface, and the application answers with a rejected login rather than a
missing variable.

The rule covers the ``mcp-`` principals only, because the registry is open by
design: an inventory contributes users of its own (the ``biber`` persona the
Playwright environments log in as is declared nowhere in ``roles/``), so a
repository-wide "every looked-up user is declared" rule would report those as
missing. The ``mcp-`` keys are role-owned, so for them the set is closed.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: user-lookup-resolves`` on, or directly above, the line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_USERS

from . import PROJECT_ROOT

_RULE = "user-lookup-resolves"
_LOOKUP = re.compile(r"""lookup\(\s*['"]users['"]\s*,\s*['"](mcp-[A-Za-z0-9_.-]+)['"]""")
_SCANNED = (".yml", ".yaml", ".j2")


def _declared_keys(roles_root: Path) -> set[str]:
    """Return every user key the roles declare."""
    keys: set[str] = set()
    for users_file in sorted(roles_root.glob(f"*/{ROLE_FILE_META_USERS}")):
        declared = load_yaml_any(str(users_file), default_if_missing={})
        if isinstance(declared, dict):
            keys |= {str(name) for name in declared}
    return keys


def _referenced_keys(roles_root: Path) -> list[tuple[str, int, str]]:
    """Return ``(path, line, key)`` for every literal mcp user lookup."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(roles_root.rglob("*")):
        if not path.is_file() or path.suffix not in _SCANNED:
            continue
        lines = read_text(str(path)).splitlines()
        for number, line in enumerate(lines, start=1):
            match = _LOOKUP.search(line)
            if not match or is_suppressed_at(lines, number, _RULE):
                continue
            found.append((str(path.relative_to(PROJECT_ROOT)), number, match.group(1)))
    return found


class TestUserLookupsResolve(unittest.TestCase):
    def test_every_looked_up_user_is_declared(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        declared = _declared_keys(roles_root)
        offenders = [
            f"{path}:{line}: lookup('users', {key!r}) addresses a service "
            f"account no meta/users.yml declares"
            for path, line, key in _referenced_keys(roles_root)
            if key not in declared
        ]
        self.assertEqual(
            [],
            offenders,
            f"unresolvable user lookup(s) ({len(offenders)}):\n"
            + "\n".join(f"  - {o}" for o in offenders),
        )

    def test_the_scan_finds_lookups(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")
        self.assertTrue(
            _referenced_keys(roles_root),
            "no role looks an mcp service account up by literal key, so the "
            "rule would pass "
            "vacuously; check that the scan still reads the right topic",
        )
