"""Unit tests for the scope of ``# variant-pin:`` in a round's assignment.

The include resolver is stubbed so each case states the round's include
directly: what matters is which roles carry a pin into the round, not how
the closure is walked.
"""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.roles.applications.variant_pins import VariantPinError
from utils.roles.applications.variants import active_variants_for_round

CARRIER = "web-app-carrier"
PARTNER = "web-app-partner"
SUBJECT = "web-app-subject"

_INCLUDE = (
    "cli.administration.deploy.development.inventory.legacy_resolver."
    "_resolve_round_include"
)


class TestPinScope(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.roles_dir = Path(tmp.name) / "roles"
        self.variants = {
            SUBJECT: [{}, {}],
            CARRIER: [{}, {"services": {"partner": {"enabled": True}}}],
            PARTNER: [{}, {}],
        }

    def write(self, role: str, name: str, body: str) -> None:
        path = self.roles_dir / role / "meta" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body))

    def assign(self, round_index: int) -> dict[str, int]:
        return active_variants_for_round(
            roles_dir=str(self.roles_dir),
            round_index=round_index,
            primary_app_variants={SUBJECT: round_index},
            variants_per_app=self.variants,
        )

    def pin_partner_from_carrier_variant_1(self) -> None:
        self.write(
            CARRIER,
            "variants.yml",
            f"""\
            - {{}}
            - services:
                # variant-pin: {PARTNER}#0
                partner:
                  enabled: true
            """,
        )

    def test_a_pin_of_a_role_outside_the_include_is_not_in_force(self) -> None:
        self.pin_partner_from_carrier_variant_1()
        with patch(_INCLUDE, autospec=True, return_value=(PARTNER, SUBJECT)):
            self.assertEqual(self.assign(1)[PARTNER], 1)

    def test_a_pin_of_a_role_inside_the_include_is_in_force(self) -> None:
        self.pin_partner_from_carrier_variant_1()
        with patch(_INCLUDE, autospec=True, return_value=(CARRIER, PARTNER, SUBJECT)):
            self.assertEqual(self.assign(1)[PARTNER], 0)

    def test_a_pin_that_drops_its_own_carrier_raises(self) -> None:
        self.write(
            CARRIER,
            "variants.yml",
            f"""\
            - services:
                # variant-pin: {PARTNER}#1
                partner:
                  enabled: true
            - {{}}
            """,
        )
        self.write(PARTNER, "services.yml", "carrier:\n  enabled: false\n")
        self.variants[PARTNER] = [
            {"services": {"carrier": {"enabled": True}}},
            {"services": {"carrier": {"enabled": False}}},
        ]

        def include(*, primary_apps, services_overrides):
            carried = services_overrides[PARTNER]["carrier"]["enabled"] is True
            return (CARRIER, PARTNER, *primary_apps) if carried else (PARTNER,)

        with (
            patch(_INCLUDE, autospec=True, side_effect=include),
            self.assertRaises(VariantPinError) as caught,
        ):
            self.assign(0)
        self.assertIn("without settling", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
