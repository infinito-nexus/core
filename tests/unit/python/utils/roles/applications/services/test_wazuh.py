from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.roles.applications.services.wazuh import rule_block_errors

_SCOPED_RULE = (
    '<group name="pixelfed,">'
    '<rule id="101001" level="5"><if_sid>101000</if_sid><match>x</match></rule>'
    "</group>"
)


class TestRuleBlockErrors(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.roles_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _ship(self, role: str, name: str, content: str) -> None:
        target = self.roles_dir / role / "files" / "wazuh"
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(content)

    def _errors(self, blocks: dict) -> list[str]:
        applications = {
            role: {"services": {"wazuh": wazuh}} for role, wazuh in blocks.items()
        }
        return rule_block_errors(applications, self.roles_dir)

    def test_valid_role_passes(self):
        self._ship("web-app-pixelfed", "rules.xml", _SCOPED_RULE)
        self._ship(
            "web-app-pixelfed",
            "decoders.xml",
            '<decoder name="pixelfed-login"><parent>infinito-pixelfed</parent></decoder>',
        )
        self.assertEqual(
            self._errors({"web-app-pixelfed": {"enabled": True, "rule_block": 101000}}),
            [],
        )

    def test_role_without_wazuh_entry_passes(self):
        self.assertEqual(rule_block_errors({"web-app-foo": {}}, self.roles_dir), [])

    def test_provider_role_is_skipped(self):
        self.assertEqual(self._errors({"web-app-wazuh": {"enabled": True}}), [])

    def test_opt_in_without_block_fails(self):
        self.assertEqual(len(self._errors({"web-app-pixelfed": {"enabled": True}})), 1)

    def test_rules_without_block_fail(self):
        self._ship("web-app-pixelfed", "rules.xml", _SCOPED_RULE)
        self.assertEqual(len(rule_block_errors({"web-app-pixelfed": {}}, self.roles_dir)), 1)

    def test_non_integer_block_fails(self):
        self.assertEqual(
            len(self._errors({"web-app-pixelfed": {"enabled": True, "rule_block": "101000"}})),
            1,
        )

    def test_block_outside_range_fails(self):
        for start in (100900, 118950, 119000):
            with self.subTest(start=start):
                self.assertEqual(
                    len(self._errors({"web-app-pixelfed": {"enabled": True, "rule_block": start}})),
                    1,
                )

    def test_overlapping_blocks_fail(self):
        errors = self._errors(
            {
                "web-app-pixelfed": {"enabled": True, "rule_block": 101000},
                "web-app-mastodon": {"enabled": True, "rule_block": 101050},
            }
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("overlap", errors[0])

    def test_adjacent_blocks_pass(self):
        self.assertEqual(
            self._errors(
                {
                    "web-app-pixelfed": {"enabled": True, "rule_block": 101000},
                    "web-app-mastodon": {"enabled": True, "rule_block": 101100},
                }
            ),
            [],
        )

    def test_rule_outside_own_block_fails(self):
        self._ship(
            "web-app-pixelfed",
            "rules.xml",
            '<rule id="101100" level="5"><if_sid>101000</if_sid></rule>',
        )
        self.assertEqual(
            len(self._errors({"web-app-pixelfed": {"enabled": True, "rule_block": 101000}})),
            1,
        )

    def test_rule_on_block_start_fails(self):
        self._ship(
            "web-app-pixelfed",
            "rules.xml",
            '<rule id="101000" level="5"><if_sid>101000</if_sid></rule>',
        )
        self.assertEqual(
            len(self._errors({"web-app-pixelfed": {"enabled": True, "rule_block": 101000}})),
            1,
        )

    def test_duplicate_rule_id_fails(self):
        self._ship("web-app-pixelfed", "rules.xml", _SCOPED_RULE + _SCOPED_RULE)
        self.assertEqual(
            len(self._errors({"web-app-pixelfed": {"enabled": True, "rule_block": 101000}})),
            1,
        )

    def test_unscoped_rule_fails(self):
        self._ship(
            "web-app-pixelfed", "rules.xml", '<rule id="101001" level="5"><match>x</match></rule>'
        )
        self.assertEqual(
            len(self._errors({"web-app-pixelfed": {"enabled": True, "rule_block": 101000}})),
            1,
        )

    def test_rule_chaining_outside_block_fails(self):
        self._ship(
            "web-app-pixelfed",
            "rules.xml",
            '<rule id="101001" level="5"><if_sid>5760, 101000</if_sid></rule>',
        )
        self.assertEqual(
            len(self._errors({"web-app-pixelfed": {"enabled": True, "rule_block": 101000}})),
            1,
        )

    def test_decoder_with_foreign_parent_fails(self):
        self._ship(
            "web-app-pixelfed",
            "decoders.xml",
            '<decoder name="pixelfed-login"><parent>sshd</parent></decoder>',
        )
        self.assertEqual(
            len(self._errors({"web-app-pixelfed": {"enabled": True, "rule_block": 101000}})),
            1,
        )

    def test_unparseable_rules_fail(self):
        self._ship("web-app-pixelfed", "rules.xml", "<rule id='101001'>")
        self.assertEqual(
            len(self._errors({"web-app-pixelfed": {"enabled": True, "rule_block": 101000}})),
            1,
        )

    def test_reserved_selftest_entity_fails(self):
        errors = self._errors(
            {"web-app-infinito-selftest": {"enabled": True, "rule_block": 101000}}
        )
        self.assertTrue(any("reserved" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
