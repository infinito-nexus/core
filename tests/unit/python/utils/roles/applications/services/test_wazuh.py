from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.roles.applications.services.wazuh import (
    DOCKER_RULE_OFFSETS,
    RESERVED_TAGS,
    docker_rule_ids,
    load_samples,
    rule_block_errors,
    tag_errors,
)

_SCOPED_RULE = (
    '<group name="pixelfed,">'
    '<rule id="101001" level="5"><if_sid>101000</if_sid><match>x</match></rule>'
    "</group>"
)
_FREQUENCY_RULE = (
    '<rule id="101002" level="10" frequency="2" timeframe="60">'
    "<if_matched_sid>101001</if_matched_sid></rule>"
)
_SAMPLE_101001 = "- log: x happened\n  rule: 101001\n  level: 5\n"
_PIXELFED = {"web-app-pixelfed": {"enabled": True, "rule_block": 101000}}


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

    def _assert_error(self, errors: list[str], fragment: str) -> None:
        self.assertTrue(
            any(fragment in error for error in errors),
            f"no error containing {fragment!r} in {errors}",
        )

    def test_valid_role_passes(self):
        self._ship("web-app-pixelfed", "rules.xml", _SCOPED_RULE)
        self._ship(
            "web-app-pixelfed",
            "decoders.xml",
            '<decoder name="pixelfed-login"><parent>infinito-pixelfed</parent></decoder>',
        )
        self._ship("web-app-pixelfed", "samples.yml", _SAMPLE_101001)
        self.assertEqual(self._errors(_PIXELFED), [])

    def test_role_without_wazuh_entry_passes(self):
        self.assertEqual(rule_block_errors({"web-app-foo": {}}, self.roles_dir), [])

    def test_provider_role_without_samples_passes(self):
        self.assertEqual(self._errors({"web-app-wazuh": {"enabled": True}}), [])

    def test_opt_in_without_block_fails(self):
        self._assert_error(
            self._errors({"web-app-pixelfed": {"enabled": True}}), "rule_block"
        )

    def test_rules_without_block_fail(self):
        self._ship("web-app-pixelfed", "rules.xml", _SCOPED_RULE)
        self._assert_error(
            rule_block_errors({"web-app-pixelfed": {}}, self.roles_dir), "rule_block"
        )

    def test_non_integer_block_fails(self):
        self._assert_error(
            self._errors(
                {"web-app-pixelfed": {"enabled": True, "rule_block": "101000"}}
            ),
            "must be an integer",
        )

    def test_block_outside_range_fails(self):
        for start in (100900, 118950, 119000):
            with self.subTest(start=start):
                self._assert_error(
                    self._errors(
                        {"web-app-pixelfed": {"enabled": True, "rule_block": start}}
                    ),
                    "is outside 101000-118999",
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
        self._assert_error(self._errors(_PIXELFED), "rule id 101100 is outside")

    def test_rule_on_block_start_fails(self):
        self._ship(
            "web-app-pixelfed",
            "rules.xml",
            '<rule id="101000" level="5"><if_sid>101000</if_sid></rule>',
        )
        self._assert_error(self._errors(_PIXELFED), "central parent rule")

    def test_rule_on_reserved_docker_ids_fails(self):
        for index, offset in enumerate(DOCKER_RULE_OFFSETS.values()):
            role, start = f"web-app-probe{index}", 101000 + index * 100
            with self.subTest(role=role):
                self._ship(
                    role,
                    "rules.xml",
                    f'<rule id="{start + offset}" level="5"><if_sid>{start}</if_sid></rule>',
                )
                self._assert_error(
                    self._errors({role: {"enabled": True, "rule_block": start}}),
                    f"rule id {start + offset} is reserved",
                )

    def test_rule_below_reserved_docker_ids_passes(self):
        self._ship(
            "web-app-pixelfed",
            "rules.xml",
            '<rule id="101095" level="5"><if_sid>101000</if_sid><match>x</match></rule>',
        )
        self._ship(
            "web-app-pixelfed", "samples.yml", "- log: x\n  rule: 101095\n  level: 5\n"
        )
        self.assertEqual(self._errors(_PIXELFED), [])

    def test_sample_on_reserved_docker_id_fails(self):
        self._ship(
            "web-app-pixelfed", "samples.yml", "- log: x\n  rule: 101099\n  level: 5\n"
        )
        self._assert_error(
            self._errors(_PIXELFED), "rule 101099 is outside 101000-101095"
        )

    def test_docker_rule_ids_sit_at_the_top_of_the_block(self):
        self.assertEqual(
            docker_rule_ids(101200),
            {"oom": 101296, "healthcheck": 101297, "swarm": 101298, "compose": 101299},
        )

    def test_duplicate_rule_id_fails(self):
        self._ship("web-app-pixelfed", "rules.xml", _SCOPED_RULE + _SCOPED_RULE)
        self._assert_error(self._errors(_PIXELFED), "defined twice")

    def test_unscoped_rule_fails(self):
        self._ship(
            "web-app-pixelfed",
            "rules.xml",
            '<rule id="101001" level="5"><match>x</match></rule>',
        )
        self._assert_error(self._errors(_PIXELFED), "not scoped")

    def test_rule_chaining_outside_block_fails(self):
        self._ship(
            "web-app-pixelfed",
            "rules.xml",
            '<rule id="101001" level="5"><if_sid>5760, 101000</if_sid></rule>',
        )
        self._assert_error(self._errors(_PIXELFED), "chains to 5760")

    def test_decoder_with_foreign_parent_fails(self):
        self._ship(
            "web-app-pixelfed",
            "decoders.xml",
            '<decoder name="pixelfed-login"><parent>sshd</parent></decoder>',
        )
        self._assert_error(self._errors(_PIXELFED), "needs <parent>infinito-pixelfed")

    def test_unparseable_rules_fail(self):
        self._ship("web-app-pixelfed", "rules.xml", "<rule id='101001'>")
        self._assert_error(self._errors(_PIXELFED), "not parseable")

    def test_provider_sample_with_own_tag_program_passes(self):
        self._ship(
            "web-app-wazuh",
            "samples.yml",
            "- log: x\n  rule: 100120\n  level: 3\n  program: infinito-deploy\n",
        )
        self.assertEqual(self._errors({"web-app-wazuh": {"enabled": True}}), [])

    def test_provider_sample_with_journald_program_passes(self):
        self._ship(
            "web-app-wazuh",
            "samples.yml",
            "- log: Suppressed 5 messages from x\n  rule: 100140\n  level: 7\n  program: systemd-journald\n",
        )
        self.assertEqual(self._errors({"web-app-wazuh": {"enabled": True}}), [])

    def test_provider_sample_with_foreign_program_fails(self):
        self._ship(
            "web-app-wazuh",
            "samples.yml",
            "- log: x\n  rule: 100120\n  level: 3\n  program: sshd\n",
        )
        self._assert_error(
            self._errors({"web-app-wazuh": {"enabled": True}}), "program must be one of"
        )

    def test_app_sample_with_program_fails(self):
        self._ship(
            "web-app-pixelfed",
            "samples.yml",
            "- log: x\n  rule: 101000\n  level: 0\n  program: infinito-deploy\n",
        )
        self._assert_error(self._errors(_PIXELFED), "exactly the keys")

    def test_rule_without_sample_fails(self):
        self._ship("web-app-pixelfed", "rules.xml", _SCOPED_RULE)
        self._assert_error(self._errors(_PIXELFED), "rule 101001 has no sample")

    def test_negative_sample_on_parent_passes(self):
        self._ship(
            "web-app-pixelfed",
            "samples.yml",
            "- log: unrelated\n  rule: 101000\n  level: 0\n",
        )
        self.assertEqual(self._errors(_PIXELFED), [])

    def test_sample_outside_own_block_fails(self):
        self._ship(
            "web-app-pixelfed", "samples.yml", "- log: x\n  rule: 100110\n  level: 3\n"
        )
        self._assert_error(
            self._errors(_PIXELFED), "rule 100110 is outside 101000-101095"
        )

    def test_sample_with_non_integer_level_fails(self):
        self._ship(
            "web-app-pixelfed",
            "samples.yml",
            "- log: x\n  rule: 101000\n  level: '0'\n",
        )
        self._assert_error(self._errors(_PIXELFED), "level must be an integer")

    def test_sample_with_multiline_log_fails(self):
        self._ship(
            "web-app-pixelfed",
            "samples.yml",
            '- log: "a\\nb"\n  rule: 101000\n  level: 0\n',
        )
        self._assert_error(self._errors(_PIXELFED), "single non-empty line")

    def test_sample_with_missing_key_fails(self):
        self._ship("web-app-pixelfed", "samples.yml", "- log: x\n  rule: 101000\n")
        self._assert_error(self._errors(_PIXELFED), "exactly the keys")

    def test_log_list_on_plain_rule_fails(self):
        self._ship("web-app-pixelfed", "rules.xml", _SCOPED_RULE)
        self._ship(
            "web-app-pixelfed",
            "samples.yml",
            "- log: [x one, x two]\n  rule: 101001\n  level: 5\n",
        )
        self._assert_error(
            self._errors(_PIXELFED), "only allowed for a correlation rule"
        )

    def test_one_item_log_list_fails(self):
        self._ship("web-app-pixelfed", "rules.xml", _SCOPED_RULE + _FREQUENCY_RULE)
        self._ship(
            "web-app-pixelfed",
            "samples.yml",
            _SAMPLE_101001 + "- log: [x one]\n  rule: 101002\n  level: 10\n",
        )
        self._assert_error(self._errors(_PIXELFED), "at least 2 lines")

    def test_log_list_on_frequency_rule_passes(self):
        self._ship("web-app-pixelfed", "rules.xml", _SCOPED_RULE + _FREQUENCY_RULE)
        self._ship(
            "web-app-pixelfed",
            "samples.yml",
            _SAMPLE_101001 + "- log: [x one, x two]\n  rule: 101002\n  level: 10\n",
        )
        self.assertEqual(self._errors(_PIXELFED), [])

    def test_provider_samples_use_the_base_range(self):
        self._ship(
            "web-app-wazuh", "samples.yml", "- log: x\n  rule: 100100\n  level: 0\n"
        )
        self.assertEqual(self._errors({"web-app-wazuh": {"enabled": True}}), [])

    def test_provider_samples_outside_base_range_fail(self):
        self._ship(
            "web-app-wazuh", "samples.yml", "- log: x\n  rule: 101000\n  level: 0\n"
        )
        self._assert_error(
            self._errors({"web-app-wazuh": {"enabled": True}}), "outside 100100-100999"
        )


class TestTagErrors(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.roles_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _errors(self, opted_in: list[str], others: tuple[str, ...] = ()) -> list[str]:
        for role in (*opted_in, *others):
            (self.roles_dir / role).mkdir(exist_ok=True)
        applications = {
            role: {"services": {"wazuh": {"enabled": True, "rule_block": 101000}}}
            for role in opted_in
        }
        applications.update({role: {} for role in others})
        return tag_errors(applications, self.roles_dir)

    def test_unique_tag_passes(self):
        self.assertEqual(self._errors(["web-app-pixelfed"], ("web-app-mastodon",)), [])

    def test_every_reserved_tag_fails(self):
        for tag in RESERVED_TAGS:
            with self.subTest(tag=tag):
                errors = self._errors([f"web-app-{tag}"])
                self.assertTrue(
                    any(f"Wazuh tag '{tag}' is reserved" in error for error in errors),
                    errors,
                )

    def test_tag_containing_systemd_fails(self):
        errors = self._errors(["web-app-systemd-exporter"])
        self.assertTrue(any("contains 'systemd'" in error for error in errors), errors)

    def test_empty_entity_fails(self):
        errors = self._errors(["update"])
        self.assertTrue(
            any("non-empty entity name" in error for error in errors), errors
        )

    def test_tag_shared_with_another_role_fails(self):
        errors = self._errors(["web-app-litellm"], ("svc-ai-litellm",))
        self.assertTrue(
            any("is also the entity of svc-ai-litellm" in error for error in errors),
            errors,
        )

    def test_shared_entity_of_roles_that_do_not_opt_in_passes(self):
        self.assertEqual(self._errors([], ("web-app-litellm", "svc-ai-litellm")), [])

    def test_provider_role_is_skipped(self):
        self.assertEqual(self._errors(["web-app-wazuh"]), [])


class TestLoadSamples(unittest.TestCase):
    def test_string_log_becomes_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "samples.yml"
            path.write_text(
                "- log: one\n  rule: 101000\n  level: 0\n"
                "- log: [a, b]\n  rule: 101002\n  level: 10\n"
                "- log: two\n  rule: 100120\n  level: 3\n  program: infinito-deploy\n"
            )
            self.assertEqual(
                load_samples(path),
                [
                    {"lines": ["one"], "rule": 101000, "level": 0},
                    {"lines": ["a", "b"], "rule": 101002, "level": 10},
                    {
                        "lines": ["two"],
                        "rule": 100120,
                        "level": 3,
                        "program": "infinito-deploy",
                    },
                ],
            )

    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_samples(Path(tmp) / "samples.yml"), [])


if __name__ == "__main__":
    unittest.main()
