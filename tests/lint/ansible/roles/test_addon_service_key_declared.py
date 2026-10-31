"""An addon may only resolve against a declared service key.

Rationale
=========
An addon reaches a role's settings through
``lookup('config', '<role>', 'services.<key>…')``. ``meta/services.yml`` of
that role is where ``<key>`` comes into existence; no other file creates one,
and a typo or a forgotten entry produces a path that resolves to nothing.

Nothing catches that at authoring time, and the two call shapes fail
differently. A two-term path is strict:
``utils/roles/applications/config.py:88`` raises ``AppConfigKeyError`` and the
deploy stops at the first host that renders the addon. A path carrying a
default is not strict, returns that default, and the addon is simply off in
every run, the same silent outcome the bridges lint exists to prevent.

``c83c00da7d`` moved twenty roles onto service keys and left
``web-app-gitlab``'s five addon keys undeclared. Nothing went red until the
deploy did.

Scope: the literal text of ``meta/addons/*.yml`` and ``tasks/addons/*.yml``.
The role argument is read as a quoted role name or as ``application_id``,
which resolves to the role owning the file. Any other variable form is
unmatched, and the second test fails on that file rather than skipping it.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_ADDON_GLOBS = ("*/meta/addons/*.yml", "*/tasks/addons/*.yml")
_SERVICES_GLOB = f"*/{ROLE_FILE_META_SERVICES}"
_REFERENCE = re.compile(
    r"lookup\(\s*'config'\s*,\s*(?:'(?P<role>[^']+)'|application_id)\s*,"
    r"\s*'services\.(?P<key>[^.']+)"
)


def _declared_services() -> dict[str, set[str]]:
    declared: dict[str, set[str]] = {}
    for path in sorted((PROJECT_ROOT / "roles").glob(_SERVICES_GLOB)):
        services = load_yaml_any(path) or {}
        declared[path.parent.parent.name] = (
            {str(key) for key, entry in services.items() if isinstance(entry, dict)}
            if isinstance(services, dict)
            else set()
        )
    return declared


def _addon_files() -> list[Path]:
    return [
        path
        for glob in _ADDON_GLOBS
        for path in sorted((PROJECT_ROOT / "roles").glob(glob))
    ]


def _references() -> Iterator[tuple[str, int, str, str]]:
    for path in _addon_files():
        text = read_text(str(path))
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        owner = path.relative_to(PROJECT_ROOT / "roles").parts[0]
        for match in _REFERENCE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            yield rel, line, match.group("role") or owner, match.group("key")


class TestAddonServiceKeyDeclared(unittest.TestCase):
    def test_every_addon_reference_names_a_declared_service(self) -> None:
        declared = _declared_services()
        findings = [
            f"  - {rel}:{line}: 'services.{key}' is not declared in "
            f"roles/{role}/{ROLE_FILE_META_SERVICES}"
            for rel, line, role, key in _references()
            if key not in declared.get(role, frozenset())
        ]

        self.assertFalse(
            findings,
            f"{len(findings)} addon reference(s) resolve against a service key "
            "that no meta/services.yml declares, so the lookup either raises "
            "AppConfigKeyError mid-deploy or silently returns its default and "
            "leaves the addon off:\n"
            + "\n".join(findings)
            + "\n\nDeclare the key in the named role's meta/services.yml, or "
            "point the lookup at the role that already carries it.",
        )

    def test_the_scan_reaches_every_referencing_file(self) -> None:
        """A regex that drifted off the call shape would pass for free."""
        self.assertTrue(_declared_services(), "no role declares services")

        matched = {rel for rel, _, _, _ in _references()}
        unmatched = sorted(
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in _addon_files()
            if "'services." in read_text(str(path))
            and path.relative_to(PROJECT_ROOT).as_posix() not in matched
        )

        self.assertTrue(matched, "the scan found no service reference at all")
        self.assertFalse(
            unmatched,
            "these addon files reference a service the pattern did not match, "
            "so the rule above skipped them:\n" + "\n".join(unmatched),
        )


if __name__ == "__main__":
    unittest.main()
