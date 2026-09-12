"""Lint: a permanently disabled services entry carries no resource weight.

``bond`` is the per-service share the resource model bills a role for. The
model never reaches it on a disabled entry:
:func:`utils.roles.applications.services.resources.collect_role_resources`
skips a service whose ``enabled`` is literally ``false`` before it reads any
resource key, so the number sits in the file describing a cost nobody pays.

Left there it reads as a live weight and outlives the reason it was written
for. An entry that was switched off because the integration cannot form keeps
claiming a share of the round's budget, which is the same statement the
``enabled`` flag was just used to withdraw.

Only a literal ``enabled: false`` is in scope. A dynamic
``"{{ '<role>' in group_names }}"`` gate is decided per round, so its ``bond``
is the weight of the rounds where the service is on.

Required
--------

For every ``services.<key>`` in a ``meta/services.yml`` whose ``enabled`` is
literally ``false``, ``bond`` MUST be absent or ``0``.

Suppression
-----------

``# nocheck: disabled-service-bond`` on the ``bond`` line, for an entry whose
weight a consumer outside the resource model still reads.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "disabled-service-bond"


def _bond_line_no(lines: list[str], key: str) -> int | None:
    """Return the 1-based line of ``key``'s ``bond``, or None when absent.

    Args:
        lines: the file's lines.
        key: the first-level service key whose block to scan.
    """
    inside = False
    for idx, line in enumerate(lines, start=1):
        if line.startswith(f"{key}:"):
            inside = True
            continue
        if inside:
            if line and not line.startswith((" ", "\t", "#")):
                return None
            if line.strip().startswith("bond:"):
                return idx
    return None


def offenders() -> list[str]:
    """Return one finding per disabled entry that still declares a bond."""
    findings: list[str] = []
    for path in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")):
        services = load_yaml_any(str(path), default_if_missing={})
        if not isinstance(services, Mapping):
            continue
        lines = read_text(str(path)).splitlines()
        role = path.parent.parent.name
        for key, entry in services.items():
            if not isinstance(entry, Mapping):
                continue
            if entry.get("enabled") is not False:
                continue
            bond = entry.get("bond")
            if bond is None or bond == 0:
                continue
            line_no = _bond_line_no(lines, str(key))
            if line_no is not None and line_has_rule(lines[line_no - 1], _RULE):
                continue
            findings.append(
                f"{role}: services.{key} is disabled but declares "
                f"bond: {bond}; the resource model skips the entry before it "
                f"reads the weight, so drop it or set it to 0"
            )
    return findings


class TestDisabledServiceBond(unittest.TestCase):
    def test_no_disabled_entry_declares_a_bond(self) -> None:
        findings = offenders()
        self.assertEqual(
            [],
            findings,
            f"disabled services entries carrying a bond ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_reaches_disabled_entries(self) -> None:
        seen = 0
        for path in sorted(
            (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
        ):
            services = load_yaml_any(str(path), default_if_missing={})
            if not isinstance(services, Mapping):
                continue
            seen += sum(
                1
                for entry in services.values()
                if isinstance(entry, Mapping) and entry.get("enabled") is False
            )
        self.assertTrue(
            seen,
            "no services entry is literally disabled, so the rule would pass "
            "vacuously; check that the scan still reads meta/services.yml",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
