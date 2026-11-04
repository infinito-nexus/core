"""Negative controls for the login-method lint."""

from __future__ import annotations

import unittest

from tests.lint.ansible.services import PROJECT_ROOT
from tests.lint.ansible.services import test_login_methods as lint
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TASKS_MAIN

ROLE = "web-app-fixture"
OBSERVED = "web-app-discourse"
MARKER = f"# nocheck: {lint.RULE}  Reason: the fixture signs in through Keycloak only"

SSO_LOOKUP = "\"{{ lookup('login_method', 'web-app-fixture', 'sso') }}\""
NATIVE_LOOKUP = "\"{{ lookup('login_method', 'web-app-fixture', 'native') }}\""

VALID = f"""---
sso:
  bond: 1
  enabled: "{{{{ 'web-app-keycloak' in group_names }}}}"
  flavor: oidc
fixture:
  image: fixture
  login:
    method:
      sso:
        enabled: {SSO_LOOKUP}
      native:
        enabled: {NATIVE_LOOKUP}
"""


def without_login(text: str) -> str:
    """*text* with the entity's ``login`` block cut.

    Args:
        text: a services file whose entity carries a ``login`` key at depth one.
    """
    lines = text.splitlines()
    start = lines.index("  login:")
    stop = start + 1
    while stop < len(lines) and lines[stop].startswith("    "):
        stop += 1
    return "\n".join(lines[:start] + lines[stop:]) + "\n"


def role_defaults(role: str, text: str) -> list[str]:
    return lint.default_findings(role, load_yaml_str(text))


def role_lacks(role: str, text: str) -> bool:
    return lint.lacks_block(role, load_yaml_str(text), text.splitlines())


def defaults(text: str) -> list[str]:
    return role_defaults(ROLE, text)


def lacks(text: str) -> bool:
    return role_lacks(ROLE, text)


class TestLoginMethodDefaults(unittest.TestCase):
    def test_a_lookup_default_passes(self) -> None:
        self.assertEqual([], defaults(VALID))

    def test_whitespace_inside_the_expression_is_tolerated(self) -> None:
        text = VALID.replace(
            NATIVE_LOOKUP,
            "\"{{   lookup('login_method', 'web-app-fixture', 'native')   }}\"",
        )
        self.assertEqual([], defaults(text))

    def test_a_literal_true_fails(self) -> None:
        findings = defaults(VALID.replace(NATIVE_LOOKUP, "true"))
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.native.enabled is True", findings[0])

    def test_a_literal_matching_one_mode_still_fails(self) -> None:
        findings = defaults(VALID.replace(NATIVE_LOOKUP, "false"))
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.native.enabled is False", findings[0])

    def test_a_hand_written_mode_condition_fails(self) -> None:
        findings = defaults(
            VALID.replace(SSO_LOOKUP, "\"{{ 'web-app-keycloak' in group_names }}\"")
        )
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.sso.enabled is", findings[0])

    def test_the_lookup_of_another_role_fails(self) -> None:
        findings = defaults(
            VALID.replace(NATIVE_LOOKUP, NATIVE_LOOKUP.replace(ROLE, "web-app-other"))
        )
        self.assertEqual(1, len(findings))
        self.assertIn("web-app-other", findings[0])

    def test_the_lookup_of_another_method_fails(self) -> None:
        findings = defaults(VALID.replace(NATIVE_LOOKUP, SSO_LOOKUP))
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.native.enabled", findings[0])

    def test_an_unknown_method_fails(self) -> None:
        text = VALID.replace("      native:", "      magic:")
        findings = defaults(text)
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.magic is not one of", findings[0])

    def test_a_method_with_a_second_key_fails(self) -> None:
        text = VALID.replace(
            f"        enabled: {NATIVE_LOOKUP}\n",
            f"        enabled: {NATIVE_LOOKUP}\n        forced: true\n",
        )
        findings = defaults(text)
        self.assertEqual(1, len(findings))
        self.assertIn("must hold exactly `enabled`", findings[0])

    def test_an_empty_method_mapping_fails(self) -> None:
        text = without_login(VALID) + "  login:\n    method: {}\n"
        self.assertEqual(
            [f"{ROLE}/fixture: login.method is not a non-empty mapping"],
            defaults(text),
        )


class TestLoginMethodScope(unittest.TestCase):
    def test_a_declared_block_satisfies_the_scope(self) -> None:
        self.assertFalse(lacks(VALID))

    def test_an_oidc_role_without_the_block_fails(self) -> None:
        self.assertTrue(lacks(without_login(VALID)))

    def test_a_saml_role_without_the_block_fails(self) -> None:
        text = without_login(VALID).replace("flavor: oidc", "flavor: saml")
        self.assertTrue(lacks(text))

    def test_an_oauth2_role_is_out_of_scope(self) -> None:
        text = without_login(VALID).replace("flavor: oidc", "flavor: oauth2")
        self.assertFalse(lacks(text))

    def test_a_block_under_another_entity_does_not_count(self) -> None:
        text = VALID.replace("fixture:\n  image: fixture", "sidecar:\n  image: fixture")
        self.assertTrue(lacks(text))

    def test_a_reasoned_marker_on_the_sso_key_exempts(self) -> None:
        text = without_login(VALID).replace("sso:\n", f"sso: {MARKER}\n", 1)
        self.assertFalse(lacks(text))

    def test_a_reasoned_marker_above_the_sso_key_exempts(self) -> None:
        text = without_login(VALID).replace("sso:\n", f"{MARKER}\nsso:\n", 1)
        self.assertFalse(lacks(text))

    def test_a_bare_marker_grants_nothing(self) -> None:
        text = without_login(VALID).replace(
            "sso:\n", f"sso: # nocheck: {lint.RULE}\n", 1
        )
        self.assertTrue(lacks(text))

    def test_a_marker_for_another_rule_grants_nothing(self) -> None:
        text = without_login(VALID).replace(
            "sso:\n", "sso: # nocheck: dynamic-flag  Reason: another rule\n", 1
        )
        self.assertTrue(lacks(text))


KEY = lint.flag_key("fixture", "native")
READER = {
    "FIXTURE_LOGIN_NATIVE": f"{{{{ lookup('config', application_id, '{KEY}') | bool }}}}"
}


class TestLoginMethodSwitch(unittest.TestCase):
    def test_an_artefact_reading_the_key_reaches(self) -> None:
        artefact = (
            f"enabled: \"{{{{ lookup('config', 'web-app-fixture', '{KEY}') }}}}\""
        )
        self.assertTrue(lint.reaches_switch(KEY, {}, [artefact]))

    def test_a_variable_an_artefact_reads_reaches(self) -> None:
        artefact = "FIXTURE_PASSWORD_LOGIN={{ FIXTURE_LOGIN_NATIVE | string | lower }}"
        self.assertTrue(lint.reaches_switch(KEY, READER, [artefact]))

    def test_a_chain_of_variables_reaches(self) -> None:
        variables = {**READER, "FIXTURE_FORM": "{{ FIXTURE_LOGIN_NATIVE | bool }}"}
        self.assertTrue(
            lint.reaches_switch(KEY, variables, ["form={{ FIXTURE_FORM }}"])
        )

    def test_a_variable_no_artefact_reads_reaches_nothing(self) -> None:
        self.assertFalse(lint.reaches_switch(KEY, READER, ["FIXTURE_OTHER=1"]))

    def test_a_longer_variable_name_is_no_read(self) -> None:
        artefact = "hint={{ FIXTURE_LOGIN_NATIVE_HINT }}"
        self.assertFalse(lint.reaches_switch(KEY, READER, [artefact]))

    def test_an_unread_key_reaches_nothing(self) -> None:
        self.assertFalse(lint.reaches_switch(KEY, {}, []))

    def test_test_and_documentation_files_carry_no_switch(self) -> None:
        for relative in (
            "templates/playwright.env.j2",
            "files/playwright/test-login-methods.js",
            "README.md",
        ):
            with self.subTest(relative=relative):
                self.assertFalse(lint.is_switch_artefact(relative))

    def test_deploy_files_carry_a_switch(self) -> None:
        for relative in (
            "templates/env.j2",
            ROLE_FILE_TASKS_MAIN,
            "meta/addons/oidc.yml",
            "files/javascript/hide-form.js",
        ):
            with self.subTest(relative=relative):
                self.assertTrue(lint.is_switch_artefact(relative))

    def test_an_unread_flag_is_a_finding(self) -> None:
        finding = lint.switch_finding(ROLE, "fixture", "native", reached=False)
        self.assertIn(f"no template, task, meta or file reads {KEY}", finding)

    def test_a_read_flag_passes(self) -> None:
        self.assertIsNone(lint.switch_finding(ROLE, "fixture", "native", reached=True))

    def test_an_unswitched_method_is_exempt(self) -> None:
        self.assertIsNone(
            lint.switch_finding("web-app-minio", "minio", "native", reached=False)
        )

    def test_a_read_unswitched_method_is_a_stale_exemption(self) -> None:
        finding = lint.switch_finding("web-app-minio", "minio", "native", reached=True)
        self.assertIn("drop it from UNSWITCHED", finding)


class TestLoginMethodSwitchObserved(unittest.TestCase):
    ROLE = "web-app-mobilizon"
    KEY = lint.flag_key("mobilizon", "native")

    def setUp(self) -> None:
        self.artefacts = lint.role_artefacts()[self.ROLE]
        self.variables = lint.role_variables(self.ROLE)

    def test_the_native_flag_reaches_the_environment(self) -> None:
        self.assertTrue(
            lint.reaches_switch(self.KEY, self.variables, self.artefacts.values())
        )

    def test_the_native_flag_reaches_nothing_without_the_environment(self) -> None:
        artefacts = {
            relative: text
            for relative, text in self.artefacts.items()
            if relative != "templates/env.j2"
        }
        self.assertFalse(
            lint.reaches_switch(self.KEY, self.variables, artefacts.values())
        )


class TestLoginMethodObserved(unittest.TestCase):
    def setUp(self) -> None:
        self.text = read_text(
            str(PROJECT_ROOT / "roles" / OBSERVED / ROLE_FILE_META_SERVICES)
        )

    def test_the_role_keeps_the_table(self) -> None:
        self.assertEqual([], role_defaults(OBSERVED, self.text))

    def test_the_role_keeps_the_block(self) -> None:
        self.assertFalse(role_lacks(OBSERVED, self.text))

    def test_the_role_fails_with_a_literal_default(self) -> None:
        text = self.text.replace(
            "\"{{ lookup('login_method', 'web-app-discourse', 'passkey') }}\"", "true"
        )
        findings = role_defaults(OBSERVED, text)
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.passkey.enabled is True", findings[0])

    def test_the_role_fails_without_its_block(self) -> None:
        self.assertTrue(role_lacks(OBSERVED, without_login(self.text)))


if __name__ == "__main__":
    unittest.main()
