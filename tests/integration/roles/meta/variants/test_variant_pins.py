"""Integration guard: every ``# variant-pin:`` resolves and points at a
variant that actually switches the pinning role back on.

Rationale
---------

``# variant-pin: <role>#<index>`` forces a partner into one variant for the
round (:mod:`utils.roles.applications.variant_pins`). The index is a position
in someone else's list: inserting a variant in the partner shifts every later
entry, and the pin then silently selects a round that does not enable the
pairing at all. Nothing at deploy time notices, because the pin resolves fine
and the inventory is written without complaint.

This guard checks the index still means what it was written to mean, by
comparing it against the variant ``#reciprocal`` would have found. A pin
written as ``#reciprocal`` carries no index, so for those the guard only
confirms the symbolic form resolves to exactly one variant.
"""

from __future__ import annotations

import unittest

from utils.cache.applications import get_variants
from utils.roles.applications.variant_pins import (
    RECIPROCAL,
    VariantPinError,
    _reciprocal_index,
    pins_of,
)

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"


def _pinning_roles() -> list[tuple[str, int, str, str]]:
    found = []
    for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
        for index, pins in pins_of(role_dir.name, roles_dir=str(ROLES_DIR)).items():
            for partner, target in sorted(pins.items()):
                found.append((role_dir.name, index, partner, target))
    return found


class TestVariantPins(unittest.TestCase):
    def test_every_pin_resolves_to_a_reciprocating_variant(self) -> None:
        variants = get_variants(roles_dir=str(ROLES_DIR))
        findings = []
        for role, index, partner, target in _pinning_roles():
            try:
                reciprocal = _reciprocal_index(
                    partner, role, roles_dir=str(ROLES_DIR), variants_per_app=variants
                )
            except VariantPinError as exc:
                findings.append(f"  - {role}#{index} -> {partner}#{target}: {exc}")
                continue
            if target != RECIPROCAL and int(target) != reciprocal:
                findings.append(
                    f"  - {role}#{index} pins {partner}#{target}, but the variant "
                    f"that switches {role} back on is {partner}#{reciprocal}"
                )

        self.assertFalse(
            findings,
            f"{len(findings)} variant pin(s) do not select a variant that "
            "reciprocates, so the round deploys the partner in a configuration "
            "that leaves the pairing dark:\n"
            + "\n".join(findings)
            + "\n\nPoint the pin at the reciprocating variant, or write it as "
            "'#reciprocal' so it follows the partner automatically.",
        )

    def test_the_scan_reads_the_marker(self) -> None:
        """A drifted marker pattern would leave nothing to check."""
        self.assertTrue(
            _pinning_roles(),
            "no role declares a '# variant-pin:' marker, so the rule above is "
            "vacuous; delete it if the mechanism is gone",
        )


if __name__ == "__main__":
    unittest.main()
