"""Negative controls for the login-method lint."""

from __future__ import annotations

import unittest
import unittest.mock as mock

from tests.lint.ansible.services import PROJECT_ROOT
from tests.lint.ansible.services import test_login_methods as lint
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TASKS_MAIN

ROLE = "web-app-fixture"
OBSERVED = "web-app-discourse"
DISCOURSE_2FA = "\"{{ lookup('login_method', 'web-app-discourse', '2fa') }}\""
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

SECOND_FACTOR_LOOKUP = "\"{{ lookup('login_method', 'web-app-fixture', '2fa') }}\""
ENFORCED = "        enforced: true\n"
VALID_2FA = VALID + f"      2fa:\n        enabled: {SECOND_FACTOR_LOOKUP}\n" + ENFORCED


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

    def test_an_enforced_second_factor_passes(self) -> None:
        self.assertEqual([], defaults(VALID_2FA))

    def test_a_second_factor_without_enforced_fails(self) -> None:
        findings = defaults(VALID_2FA.replace(ENFORCED, ""))
        self.assertEqual(1, len(findings))
        self.assertIn(
            "login.method.2fa must hold exactly `enabled` and `enforced`", findings[0]
        )

    def test_an_enforced_default_other_than_true_fails(self) -> None:
        for value in (
            "false",
            '"true"',
            "1",
            "\"{{ 'web-app-keycloak' in group_names }}\"",
        ):
            with self.subTest(value=value):
                findings = defaults(
                    VALID_2FA.replace(ENFORCED, f"        enforced: {value}\n")
                )
                self.assertEqual(1, len(findings))
                self.assertIn("login.method.2fa.enforced is", findings[0])

    def test_an_offered_only_role_defaults_to_false(self) -> None:
        offered = VALID_2FA.replace(ENFORCED, "        enforced: false\n")
        with mock.patch.dict(
            lint.OFFERED_ONLY, {ROLE: "the fixture's bot cannot enroll"}
        ):
            self.assertEqual([], defaults(offered))
            findings = defaults(VALID_2FA)
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.2fa.enforced is True, expected False", findings[0])

    def test_a_native_beside_sso_role_defaults_native_to_true(self) -> None:
        kept = VALID.replace(NATIVE_LOOKUP, "true")
        with mock.patch.dict(
            lint.NATIVE_BESIDE_SSO, {ROLE: "the fixture's SSO link sits on the form"}
        ):
            self.assertEqual([], defaults(kept))
            findings = defaults(VALID)
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.native.enabled is", findings[0])
        self.assertIn("expected True", findings[0])

    def _assert_enforces_by_default(self, role: str) -> None:
        text = read_text(str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES))
        self.assertNotIn(role, lint.OFFERED_ONLY)
        self.assertEqual([], role_defaults(role, text))
        offered = text.replace(
            "'2fa') }}\"\n        enforced: true\n",
            "'2fa') }}\"\n        enforced: false\n",
        )
        self.assertNotEqual(text, offered)
        findings = role_defaults(role, offered)
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.2fa.enforced is False, expected True", findings[0])

    def test_moodle_enforces_its_second_factor_by_default(self) -> None:
        self._assert_enforces_by_default("web-app-moodle")

    def test_matomo_enforces_its_second_factor_by_default(self) -> None:
        self._assert_enforces_by_default("web-app-matomo")

    def test_weblate_enforces_its_second_factor_by_default(self) -> None:
        self._assert_enforces_by_default("web-app-weblate")

    def test_enforced_on_another_method_fails(self) -> None:
        text = VALID.replace(
            f"        enabled: {NATIVE_LOOKUP}\n",
            f"        enabled: {NATIVE_LOOKUP}\n        enforced: true\n",
        )
        findings = defaults(text)
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.native must hold exactly `enabled`", findings[0])

    def test_an_empty_method_mapping_fails(self) -> None:
        text = without_login(VALID) + "  login:\n    method: {}\n"
        self.assertEqual(
            [f"{ROLE}/fixture: login.method is not a non-empty mapping"],
            defaults(text),
        )


SSO_ON = {"services": {"sso": {"enabled": True, "shared": True}}}
SSO_OFF = {"services": {"sso": {"enabled": False, "shared": False}}}
ENFORCEMENT_OFF = {"fixture": {"login": {"method": {"2fa": {"enforced": False}}}}}


def sso_off(**services: object) -> dict:
    return {"services": {**SSO_OFF["services"], **services}}


class TestLoginMethodVariants(unittest.TestCase):
    def test_the_entities_with_a_second_factor_are_found(self) -> None:
        self.assertEqual(
            ["fixture"], lint.second_factor_entities(load_yaml_str(VALID_2FA))
        )
        self.assertEqual([], lint.second_factor_entities(load_yaml_str(VALID)))

    def test_a_variant_without_sso_that_switches_enforcement_off_passes(self) -> None:
        variants = [SSO_ON, sso_off(**ENFORCEMENT_OFF)]
        self.assertEqual([], lint.variant_findings(ROLE, "fixture", variants))

    def test_a_variant_without_sso_that_keeps_enforcement_fails(self) -> None:
        findings = lint.variant_findings(ROLE, "fixture", [SSO_ON, SSO_OFF])
        self.assertEqual(1, len(findings))
        self.assertIn(f"{ROLE} variant 1: SSO is off", findings[0])
        self.assertIn("services.fixture.login.method.2fa.enforced: false", findings[0])

    def test_an_enforcement_left_on_fails(self) -> None:
        kept = {"fixture": {"login": {"method": {"2fa": {"enforced": True}}}}}
        findings = lint.variant_findings(ROLE, "fixture", [sso_off(**kept)])
        self.assertEqual(1, len(findings))

    def test_the_enforcement_of_another_entity_does_not_count(self) -> None:
        other = {"sidecar": ENFORCEMENT_OFF["fixture"]}
        findings = lint.variant_findings(ROLE, "fixture", [sso_off(**other)])
        self.assertEqual(1, len(findings))

    def test_a_variant_with_sso_on_needs_nothing(self) -> None:
        self.assertEqual([], lint.variant_findings(ROLE, "fixture", [SSO_ON, {}]))

    def test_a_non_literal_sso_off_needs_the_switch_too(self) -> None:
        for value in ("false", "False", "no", "{{ false }}", "{{ 'false' }}"):
            with self.subTest(value=value):
                variant = {"services": {"sso": {"enabled": value}}}
                findings = lint.variant_findings(ROLE, "fixture", [variant])
                self.assertEqual(1, len(findings))
                variant["services"].update(ENFORCEMENT_OFF)
                self.assertEqual([], lint.variant_findings(ROLE, "fixture", [variant]))

    def test_a_non_literal_enforcement_off_counts(self) -> None:
        off = {"fixture": {"login": {"method": {"2fa": {"enforced": "{{ false }}"}}}}}
        self.assertEqual([], lint.variant_findings(ROLE, "fixture", [sso_off(**off)]))

    def test_true_and_unknown_values_are_not_off(self) -> None:
        for value in (True, None, "true", "{{ true }}", "{{ sso_flag }}", 1):
            with self.subTest(value=value):
                self.assertFalse(lint.is_false(value))

    def test_the_observed_role_fails_without_its_variant_switch(self) -> None:
        text = read_text(
            str(PROJECT_ROOT / "roles" / OBSERVED / lint.ROLE_FILE_META_VARIANTS)
        )
        self.assertEqual(
            [], lint.variant_findings(OBSERVED, "discourse", load_yaml_str(text))
        )
        stripped = text.replace(
            "            enforced: false\n", "            enforced: true\n"
        )
        findings = lint.variant_findings(OBSERVED, "discourse", load_yaml_str(stripped))
        self.assertEqual(2, len(findings))


VARIANT_MARKER = (
    f"# nocheck: {lint.RULE}  Reason: the fixture's spec proves the enrollment"
)
KEPT_ENFORCEMENT = """---
- services:
    sso:
      enabled: true
      shared: true
- services:
    fixture:
      login:
        method:
          2fa:
            enforced: true
    sso:
      enabled: false
      shared: false
"""
KEPT_LINE = "            enforced: true\n"


def marked(marker: str) -> str:
    return KEPT_ENFORCEMENT.replace(KEPT_LINE, f"            enforced: true {marker}\n")


def kept_findings(role: str, entity: str, text: str) -> list[str]:
    kept = lint.enforcement_kept(text, entity)
    return lint.variant_findings(role, entity, load_yaml_str(text), kept)


class TestLoginMethodEnforcementVariant(unittest.TestCase):
    def test_an_unmarked_enforcement_without_sso_fails(self) -> None:
        self.assertEqual(1, len(kept_findings(ROLE, "fixture", KEPT_ENFORCEMENT)))

    def test_a_reasoned_marker_on_the_enforced_key_keeps_it(self) -> None:
        text = marked(VARIANT_MARKER)
        self.assertEqual(frozenset({1}), lint.enforcement_kept(text, "fixture"))
        self.assertEqual([], kept_findings(ROLE, "fixture", text))

    def test_a_reasoned_marker_above_the_enforced_key_keeps_it(self) -> None:
        text = KEPT_ENFORCEMENT.replace(
            KEPT_LINE, f"            {VARIANT_MARKER}\n{KEPT_LINE}"
        )
        self.assertEqual([], kept_findings(ROLE, "fixture", text))

    def test_a_bare_marker_keeps_nothing(self) -> None:
        text = marked(f"# nocheck: {lint.RULE}")
        self.assertEqual(frozenset(), lint.enforcement_kept(text, "fixture"))
        self.assertEqual(1, len(kept_findings(ROLE, "fixture", text)))

    def test_a_marker_on_another_key_keeps_nothing(self) -> None:
        text = KEPT_ENFORCEMENT.replace(
            "    sso:\n      enabled: false",
            f"    sso: {VARIANT_MARKER}\n      enabled: false",
        )
        self.assertEqual(1, len(kept_findings(ROLE, "fixture", text)))

    def test_the_marker_keeps_only_its_own_entity(self) -> None:
        self.assertEqual(
            frozenset(), lint.enforcement_kept(marked(VARIANT_MARKER), "sidecar")
        )

    def test_a_marker_on_a_switched_off_enforcement_is_a_finding(self) -> None:
        text = marked(VARIANT_MARKER).replace("enforced: true", "enforced: false")
        findings = kept_findings(ROLE, "fixture", text)
        self.assertEqual(1, len(findings))
        self.assertIn(
            f"{ROLE} variant 1: its `nocheck: {lint.RULE}` marker", findings[0]
        )

    def test_a_marker_on_a_variant_with_sso_on_is_a_finding(self) -> None:
        text = marked(VARIANT_MARKER).replace(
            "      enabled: false\n      shared: false\n",
            "      enabled: true\n      shared: true\n",
        )
        findings = kept_findings(ROLE, "fixture", text)
        self.assertEqual(1, len(findings))
        self.assertIn("keeps no enforcement on", findings[0])

    def test_a_second_marked_variant_of_the_role_is_a_finding(self) -> None:
        proof = marked(VARIANT_MARKER).split("- services:\n")[2]
        text = f"{marked(VARIANT_MARKER)}- services:\n{proof}"
        self.assertEqual(frozenset({1, 2}), lint.enforcement_kept(text, "fixture"))
        findings = kept_findings(ROLE, "fixture", text)
        self.assertEqual(1, len(findings))
        self.assertIn(f"{ROLE} variants 1, 2: only one variant per role", findings[0])

    def test_the_matomo_enforcement_variant_passes_only_with_its_marker(self) -> None:
        role = "web-app-matomo"
        text = read_text(
            str(PROJECT_ROOT / "roles" / role / lint.ROLE_FILE_META_VARIANTS)
        )
        self.assertEqual(frozenset({2}), lint.enforcement_kept(text, "matomo"))
        self.assertEqual([], kept_findings(role, "matomo", text))
        unmarked = "".join(
            line
            for line in text.splitlines(keepends=True)
            if f"nocheck: {lint.RULE}" not in line
        )
        self.assertNotEqual(text, unmarked)
        expected = (
            f"{role} variant 2: SSO is off, so it sets "
            "services.matomo.login.method.2fa.enforced: false"
        )
        self.assertEqual([expected], kept_findings(role, "matomo", unmarked))


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

    def test_the_role_enforces_its_second_factor(self) -> None:
        (second_factor,) = [
            entity["login"]["method"]["2fa"]
            for entity in load_yaml_str(self.text).values()
            if isinstance(entity, dict) and "login" in entity
        ]
        self.assertEqual(
            second_factor,
            {"enabled": DISCOURSE_2FA.strip('"'), "enforced": True},
        )

    def test_the_role_fails_without_enforced(self) -> None:
        text = self.text.replace(f"{DISCOURSE_2FA}\n{ENFORCED}", f"{DISCOURSE_2FA}\n")
        findings = role_defaults(OBSERVED, text)
        self.assertEqual(1, len(findings))
        self.assertIn("login.method.2fa must hold exactly", findings[0])


if __name__ == "__main__":
    unittest.main()
