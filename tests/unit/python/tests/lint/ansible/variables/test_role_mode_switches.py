"""Negative controls for the role mode-switch lint."""

from __future__ import annotations

import unittest

from tests.lint.ansible.variables import test_role_mode_switches as lint
from utils.cache.yaml import load_yaml_str

ROLE = "web-app-fixture"
ENTITY = "fixture"

OVERRIDDEN = """---
fixture:
  debug:
    enabled: true
  validate:
    enabled: "{{ lookup('env', 'FIXTURE_VALIDATE') | bool }}"
  image: fixture
"""

DEBUG_READ = "{{ lookup('debug') | bool }}"
VALIDATE_READ = "when: lookup('validate', 'web-app-fixture')"


def services(text: str) -> object:
    return load_yaml_str(text)


def findings(text: str, *reads: str, has_application_id: bool = True) -> list[str]:
    read, read_findings = lint.read_switches(ROLE, has_application_id, reads)
    return read_findings + lint.declaration_findings(ROLE, ENTITY, services(text), read)


def yaml_reads(text: str) -> list[int]:
    return lint.global_read_lines(text, yaml_file=True)


def template_reads(text: str) -> list[int]:
    return lint.global_read_lines(text, yaml_file=False)


class TestGlobalReads(unittest.TestCase):
    def test_a_template_reading_debug_is_found(self) -> None:
        self.assertEqual([2], template_reads("a: 1\nb: {{ DEBUG }}\n"))

    def test_a_statement_reading_validate_is_found(self) -> None:
        self.assertEqual([1], template_reads("{% if VALIDATE | bool %}x{% endif %}\n"))

    def test_a_multi_line_expression_is_found_at_its_start(self) -> None:
        self.assertEqual([1], template_reads("{{ 'a'\n   if DEBUG\n   else 'b' }}\n"))

    def test_an_inline_condition_is_found(self) -> None:
        self.assertEqual([2], yaml_reads("- name: x\n  when: VALIDATE | bool\n"))

    def test_a_quoted_condition_is_found(self) -> None:
        self.assertEqual([1], yaml_reads('when: "DEBUG | bool"\n'))

    def test_a_list_condition_is_found(self) -> None:
        text = "- name: x\n  when:\n    - other\n    - DEBUG | bool\n- name: y\n"
        self.assertEqual([4], yaml_reads(text))

    def test_a_list_condition_at_the_key_indent_is_found(self) -> None:
        text = "- name: x\n  failed_when:\n  - not (VALIDATE | bool)\n  tags: a\n"
        self.assertEqual([3], yaml_reads(text))

    def test_a_folded_condition_is_found(self) -> None:
        text = "- name: x\n  until: >-\n    a and\n    DEBUG | bool\n"
        self.assertEqual([4], yaml_reads(text))

    def test_an_assert_that_is_found(self) -> None:
        text = "- assert:\n    that:\n      - VALIDATE\n"
        self.assertEqual([3], yaml_reads(text))

    def test_a_condition_ends_at_the_next_key(self) -> None:
        text = "- name: x\n  when: a\n  vars:\n    DEBUG_LEVEL: DEBUG\n"
        self.assertEqual([], yaml_reads(text))

    def test_a_comment_line_is_not_a_read(self) -> None:
        self.assertEqual([], yaml_reads("# when: VALIDATE | bool\n"))
        self.assertEqual([], template_reads("# {{ DEBUG }}\n"))

    def test_a_trailing_comment_is_not_a_read(self) -> None:
        self.assertEqual([], yaml_reads("when: a | bool  # gated by DEBUG\n"))

    def test_a_jinja_comment_is_not_a_read(self) -> None:
        self.assertEqual([], template_reads("{# follows DEBUG #}\n{{ x }}\n"))

    def test_a_string_literal_is_not_a_read(self) -> None:
        self.assertEqual(
            [], template_reads("LEVEL={{ 'DEBUG' if lookup('debug') else 'INFO' }}\n")
        )

    def test_text_outside_jinja_is_not_a_read(self) -> None:
        self.assertEqual([], template_reads("DEBUG=1\nif (DEBUG) console.log(x);\n"))

    def test_a_longer_or_dotted_name_is_not_a_read(self) -> None:
        self.assertEqual(
            [], template_reads("{{ J_DEBUG }} {{ DEBUG_X }} {{ logging.DEBUG }}\n")
        )

    def test_a_condition_key_is_ignored_outside_yaml(self) -> None:
        self.assertEqual([], template_reads("when: DEBUG\n"))

    def test_an_override_reading_the_global_is_found(self) -> None:
        text = '---\nfixture:\n  debug:\n    enabled: "{{ DEBUG | bool }}"\n'
        self.assertEqual(
            ["fixture.debug.enabled"], lint.services_global_reads(services(text))
        )

    def test_a_global_read_elsewhere_in_services_is_found(self) -> None:
        text = OVERRIDDEN + '  verbose: "{{ VALIDATE | bool }}"\n'
        self.assertEqual(
            ["fixture.verbose"], lint.services_global_reads(services(text))
        )

    def test_a_literal_or_independent_override_is_no_read(self) -> None:
        self.assertEqual([], lint.services_global_reads(services(OVERRIDDEN)))


class TestSwitchReadsAndOverrides(unittest.TestCase):
    def test_lookups_without_override_pass(self) -> None:
        text = "---\nfixture:\n  image: fixture\n"
        self.assertEqual([], findings(text, DEBUG_READ, VALIDATE_READ))

    def test_overrides_with_their_lookups_pass(self) -> None:
        self.assertEqual([], findings(OVERRIDDEN, DEBUG_READ, VALIDATE_READ))

    def test_an_override_nobody_reads_is_dead_config(self) -> None:
        self.assertEqual(
            [
                (
                    f"{ROLE}: declares fixture.validate, but its code never calls "
                    "lookup('validate') (dead config)"
                )
            ],
            findings(OVERRIDDEN, DEBUG_READ),
        )

    def test_a_read_through_config_fails(self) -> None:
        read = (
            "{{ lookup('config', application_id, 'services.fixture.debug.enabled') }}"
        )
        self.assertIn(
            f"{ROLE}: reads the debug switch through lookup('config'), call "
            "lookup('debug') instead",
            findings(OVERRIDDEN, read, VALIDATE_READ),
        )

    def test_extra_keys_under_an_override_fail(self) -> None:
        text = OVERRIDDEN.replace(
            "    enabled: true\n", "    enabled: true\n    level: 3\n"
        )
        self.assertEqual(
            [f"{ROLE}: fixture.debug must hold exactly `enabled`"],
            findings(text, DEBUG_READ, VALIDATE_READ),
        )

    def test_an_override_on_a_secondary_entity_fails(self) -> None:
        text = OVERRIDDEN + "worker:\n  debug:\n    enabled: true\n"
        self.assertIn(
            f"{ROLE}: declares worker.debug, only the primary entity fixture carries it",
            findings(text, DEBUG_READ, VALIDATE_READ),
        )

    def test_reading_another_role_fails(self) -> None:
        read = VALIDATE_READ.replace("'web-app-fixture'", "'web-app-other'")
        self.assertIn(
            f"{ROLE}: reads the validate switch of web-app-other",
            findings(OVERRIDDEN, DEBUG_READ, read),
        )

    def test_an_expression_as_role_fails(self) -> None:
        read = "{{ lookup('debug', application_id) }}"
        self.assertIn(
            f"{ROLE}: lookup('debug' , application_id) names the role through an "
            f"expression, call lookup('debug') or lookup('debug', '{ROLE}')",
            findings(OVERRIDDEN, read, VALIDATE_READ),
        )

    def test_no_term_in_a_role_without_application_id_fails(self) -> None:
        self.assertIn(
            f"{ROLE}: defines no application_id, call lookup('debug', '{ROLE}')",
            findings(OVERRIDDEN, DEBUG_READ, VALIDATE_READ, has_application_id=False),
        )

    def test_the_literal_role_passes_without_application_id(self) -> None:
        read = "{{ lookup('debug', 'web-app-fixture') }}"
        self.assertEqual(
            [],
            findings(OVERRIDDEN, read, VALIDATE_READ, has_application_id=False),
        )


if __name__ == "__main__":
    unittest.main()
