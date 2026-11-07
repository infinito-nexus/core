from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli.meta.ci.variant_split import rounds
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

CARRIER = """\
- services:
    # variant-pin: web-app-b#TARGET
    b:
      enabled: true
      shared: true
"""
PARTNER = """\
a:
  enabled: "{{ 'web-app-a' in group_names }}"
  shared: "{{ 'web-app-a' in group_names }}"
"""


def _tree(tmp: str, target: str, gate: bool = True) -> str:
    root = Path(tmp)
    (root / "web-app-a" / "meta").mkdir(parents=True)
    (root / "web-app-b" / "meta").mkdir(parents=True)
    (root / "web-app-a" / ROLE_FILE_META_VARIANTS).write_text(
        CARRIER.replace("TARGET", target)
    )
    (root / "web-app-b" / ROLE_FILE_META_SERVICES).write_text(
        PARTNER if gate else "c: {}\n"
    )
    return tmp


VARIANTS = {
    "web-app-b": [
        {"services": {"a": {"enabled": False}}},
        {"services": {"a": {"enabled": True}}},
    ]
}


class TestPins(unittest.TestCase):
    def test_a_pin_is_read_with_the_key_it_stands_above(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                rounds.pinned_keys("web-app-a", _tree(tmp, "1")),
                {0: {"web-app-b": ("1", "b")}},
            )

    def test_a_reciprocating_pin_names_its_partner_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [finding] = rounds.pin_findings(
                "web-app-a", roles_dir=_tree(tmp, "1"), variants_per_app=VARIANTS
            )
        self.assertEqual((finding["target"], finding["reciprocal"]), ("1", 1))

    def test_negative_control_a_pin_at_the_wrong_index_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [finding] = rounds.pin_findings(
                "web-app-a", roles_dir=_tree(tmp, "0"), variants_per_app=VARIANTS
            )
        self.assertEqual((finding["target"], finding["reciprocal"]), ("0", 1))

    def test_negative_control_a_partner_without_a_back_gate_cannot_reciprocate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [finding] = rounds.pin_findings(
                "web-app-a",
                roles_dir=_tree(tmp, "1", gate=False),
                variants_per_app=VARIANTS,
            )
        self.assertTrue(str(finding["reciprocal"]).startswith("error:"))


class TestToken(unittest.TestCase):
    def test_a_whole_role_row_is_variant_0(self) -> None:
        self.assertEqual(rounds.token("web-app-a", None), "web-app-a#0")

    def test_a_variant_row_keeps_its_index(self) -> None:
        self.assertEqual(rounds.token("web-app-a", 3), "web-app-a#3")


class TestDictated(unittest.TestCase):
    def setUp(self) -> None:
        rounds._dictating.cache_clear()
        self.addCleanup(rounds._dictating.cache_clear)

    def _dictated(self, include: list[str], active: dict[str, int]) -> dict:
        found = {("web-app-a", 1): {"web-app-b", "web-app-gone"}}
        with mock.patch.object(rounds, "overridden_providers", return_value=found):
            return rounds.dictated(include, active, roles_dir="/roles")

    def test_a_member_whose_config_a_variant_dictates_names_that_variant(
        self,
    ) -> None:
        found = self._dictated(["web-app-b", "web-app-a"], {"web-app-a": 1})
        self.assertEqual(found, {"web-app-b": "web-app-a#1"})

    def test_negative_control_another_variant_of_the_carrier_dictates_nothing(
        self,
    ) -> None:
        self.assertEqual(
            self._dictated(["web-app-b", "web-app-a"], {"web-app-a": 0}), {}
        )


if __name__ == "__main__":
    unittest.main()
