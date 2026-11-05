"""Unit tests for ``# variant-pin:`` parsing and resolution."""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.roles.applications.variant_pins import (
    VariantPinConflictError,
    VariantPinError,
    pins_of,
    resolve_pins,
)

OPENPROJECT_VARIANTS = """\
---
- services:
    nextcloud:
      enabled: false
- services:
    # variant-pin: web-app-nextcloud#{target}
    nextcloud:
      enabled: true
    gitlab:
      enabled: false
"""

NEXTCLOUD_SERVICES = """\
---
openproject:
  enabled: "{{ 'web-app-openproject' in group_names }}"
matomo:
  enabled: "{{ 'web-app-matomo' in group_names }}"
"""

GITLAB_VARIANTS = """\
---
- services:
    # variant-pin: web-app-nextcloud#{target}
    nextcloud:
      enabled: true
"""


class VariantPinTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.roles_dir = str(self.root / "roles")
        self.write("web-app-nextcloud", "services.yml", NEXTCLOUD_SERVICES)
        self.variants: dict[str, list[dict]] = {
            "web-app-openproject": [{}, {}],
            "web-app-nextcloud": [
                {"services": {"openproject": {"enabled": False}}},
                {"services": {"openproject": {"enabled": False}}},
                {"services": {"openproject": {"enabled": False}}},
                {"services": {"openproject": {"enabled": True}}},
            ],
        }
        self.addCleanup(self._tmp.cleanup)

    def write(self, role: str, name: str, body: str) -> None:
        path = self.root / "roles" / role / "meta" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    def pin_openproject(self, target: str) -> None:
        self.write(
            "web-app-openproject",
            "variants.yml",
            OPENPROJECT_VARIANTS.format(target=target),
        )

    def pin_gitlab(self, target: str) -> None:
        self.write(
            "web-app-gitlab", "variants.yml", GITLAB_VARIANTS.format(target=target)
        )
        self.variants["web-app-gitlab"] = [{}]

    def resolve(self, active: dict[str, int]) -> dict[str, int]:
        return resolve_pins(
            active, roles_dir=self.roles_dir, variants_per_app=self.variants
        )

    def test_the_marker_binds_to_the_entry_below_it(self) -> None:
        self.pin_openproject("3")
        self.assertEqual(
            pins_of("web-app-openproject", roles_dir=self.roles_dir),
            {1: {"web-app-nextcloud": "3"}},
        )

    def test_the_symbolic_target_survives_parsing(self) -> None:
        self.pin_openproject("reciprocal")
        self.assertEqual(
            pins_of("web-app-openproject", roles_dir=self.roles_dir),
            {1: {"web-app-nextcloud": "reciprocal"}},
        )

    def test_a_role_without_variants_contributes_nothing(self) -> None:
        self.assertEqual(pins_of("web-app-absent", roles_dir=self.roles_dir), {})

    def test_a_marker_without_an_entry_below_it_is_ignored(self) -> None:
        self.write(
            "web-app-openproject",
            "variants.yml",
            textwrap.dedent("""\
                ---
                # variant-pin: web-app-nextcloud#3
                - services:
                    nextcloud:
                      enabled: true
                """),
        )
        self.assertEqual(pins_of("web-app-openproject", roles_dir=self.roles_dir), {})

    def test_an_active_variant_applies_its_index_pin(self) -> None:
        self.pin_openproject("3")
        self.assertEqual(
            self.resolve({"web-app-openproject": 1}), {"web-app-nextcloud": 3}
        )

    def test_reciprocal_finds_the_variant_switching_this_role_on(self) -> None:
        self.pin_openproject("reciprocal")
        self.assertEqual(
            self.resolve({"web-app-openproject": 1}), {"web-app-nextcloud": 3}
        )

    def test_a_variant_the_round_does_not_run_is_ignored(self) -> None:
        self.pin_openproject("3")
        self.assertEqual(self.resolve({"web-app-openproject": 0}), {})

    def test_an_out_of_range_index_raises(self) -> None:
        self.pin_openproject("3")
        self.variants["web-app-nextcloud"] = self.variants["web-app-nextcloud"][:2]
        with self.assertRaises(VariantPinError) as caught:
            self.resolve({"web-app-openproject": 1})
        self.assertIn("declares 2 variant(s)", str(caught.exception))

    def test_reciprocal_without_a_candidate_raises(self) -> None:
        self.pin_openproject("reciprocal")
        self.variants["web-app-nextcloud"] = self.variants["web-app-nextcloud"][:2]
        with self.assertRaises(VariantPinError) as caught:
            self.resolve({"web-app-openproject": 1})
        self.assertIn("reciprocal needs exactly one", str(caught.exception))

    def test_reciprocal_with_two_candidates_raises(self) -> None:
        self.pin_openproject("reciprocal")
        self.variants["web-app-nextcloud"][0] = {
            "services": {"openproject": {"enabled": True}}
        }
        with self.assertRaises(VariantPinError) as caught:
            self.resolve({"web-app-openproject": 1})
        self.assertIn("in 2 variants", str(caught.exception))

    def test_reciprocal_without_a_back_reference_raises(self) -> None:
        self.pin_openproject("reciprocal")
        self.write(
            "web-app-nextcloud", "services.yml", "---\nmatomo:\n  enabled: true\n"
        )
        with self.assertRaises(VariantPinError) as caught:
            self.resolve({"web-app-openproject": 1})
        self.assertIn("declares no service gating on", str(caught.exception))

    def test_two_roles_pinning_one_partner_differently_raises(self) -> None:
        self.pin_openproject("3")
        self.pin_gitlab("1")
        with self.assertRaises(VariantPinConflictError) as caught:
            self.resolve({"web-app-openproject": 1, "web-app-gitlab": 0})
        self.assertIn(
            "cannot deploy web-app-nextcloud in two variants", str(caught.exception)
        )

    def test_agreeing_pins_do_not_conflict(self) -> None:
        self.pin_openproject("3")
        self.pin_gitlab("3")
        self.assertEqual(
            self.resolve({"web-app-openproject": 1, "web-app-gitlab": 0}),
            {"web-app-nextcloud": 3},
        )

    def test_an_index_pin_and_a_reciprocal_pin_agreeing_do_not_conflict(self) -> None:
        self.pin_openproject("reciprocal")
        self.pin_gitlab("3")
        self.assertEqual(
            self.resolve({"web-app-openproject": 1, "web-app-gitlab": 0}),
            {"web-app-nextcloud": 3},
        )


if __name__ == "__main__":
    unittest.main()
