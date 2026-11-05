"""Semaphore's variant matrix: everything on, docs alone, LDAP alone, onion always."""

from __future__ import annotations

import copy
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
ALWAYS_ON = "tor"
GUIDE = "docs"
LDAP_ROUND = frozenset({"ldap", "lam"})


def _yaml(relative: str):
    return load_yaml_str(read_text(str(ROLE / relative)))


def integration_flags(base: dict, variants: list) -> set[str]:
    """The service flags a variant switches, without the role's own entities.

    Args:
        base: the role's ``meta/services.yml``.
        variants: the entries of its ``meta/variants.yml``.

    Returns:
        Keys whose ``enabled`` follows ``group_names`` in ``base``, plus keys
        only a variant declares.
    """
    dynamic = {
        key
        for key, entry in base.items()
        if isinstance(entry, dict) and "group_names" in str(entry.get("enabled", ""))
    }
    declared = {key for variant in variants for key in variant.get("services", {})}
    return (dynamic | (declared - set(base))) - {ALWAYS_ON}


def enabled_flags(variant: dict, flags: set[str]) -> set[str]:
    """The flags a variant sets to a literal ``true``.

    Args:
        variant: one entry of ``meta/variants.yml``.
        flags: the flags to inspect.
    """
    services = variant.get("services", {})
    return {key for key in flags if (services.get(key) or {}).get("enabled") is True}


def matrix_findings(base: dict, variants: list) -> list[str]:
    """Deviations from the V1 / V2 / V3 matrix.

    Args:
        base: the role's ``meta/services.yml``.
        variants: the entries of its ``meta/variants.yml``.

    Returns:
        One message per deviation, empty when the matrix holds.
    """
    if len(variants) != 3:
        return [f"expected exactly three variants, found {len(variants)}"]
    flags = integration_flags(base, variants)
    expected = (flags - {GUIDE}, {GUIDE}, set(LDAP_ROUND))
    findings = []
    for index, (variant, want) in enumerate(zip(variants, expected, strict=True)):
        got = enabled_flags(variant, flags)
        if got != want:
            findings.append(
                f"V{index + 1} enables {sorted(got)}, expected {sorted(want)}"
            )
        tor = (variant.get("services", {}).get(ALWAYS_ON) or {}).get("enabled")
        if tor is not True:
            findings.append(f"V{index + 1} does not keep {ALWAYS_ON} on")
    return findings


class TestVariantMatrix(unittest.TestCase):
    def setUp(self):
        self.base = _yaml(ROLE_FILE_META_SERVICES)
        self.variants = _yaml(ROLE_FILE_META_VARIANTS)

    def test_the_shipped_matrix_holds(self):
        self.assertEqual(matrix_findings(self.base, self.variants), [])

    def test_the_matrix_covers_the_ldap_round_and_the_integrations(self):
        flags = integration_flags(self.base, self.variants)
        self.assertLessEqual(LDAP_ROUND, flags)
        self.assertLessEqual({"sso", "gitea", GUIDE}, flags)

    def test_a_fourth_variant_is_reported(self):
        variants = [*self.variants, copy.deepcopy(self.variants[1])]
        self.assertEqual(
            matrix_findings(self.base, variants),
            ["expected exactly three variants, found 4"],
        )

    def test_sso_in_the_ldap_round_is_reported(self):
        variants = copy.deepcopy(self.variants)
        variants[2]["services"]["sso"]["enabled"] = True
        self.assertEqual(len(matrix_findings(self.base, variants)), 1)

    def test_an_integration_switched_on_beside_docs_is_reported(self):
        variants = copy.deepcopy(self.variants)
        variants[1]["services"]["gitea"]["enabled"] = True
        self.assertEqual(len(matrix_findings(self.base, variants)), 1)

    def test_an_integration_missing_from_the_full_round_is_reported(self):
        variants = copy.deepcopy(self.variants)
        variants[0]["services"]["ldap"]["enabled"] = False
        self.assertEqual(len(matrix_findings(self.base, variants)), 1)

    def test_the_onion_switched_off_is_reported(self):
        variants = copy.deepcopy(self.variants)
        variants[2]["services"][ALWAYS_ON]["enabled"] = False
        self.assertEqual(
            matrix_findings(self.base, variants), ["V3 does not keep tor on"]
        )


if __name__ == "__main__":
    unittest.main()
