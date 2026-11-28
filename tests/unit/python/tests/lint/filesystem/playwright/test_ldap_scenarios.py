"""Fixtures and negative controls for the LDAP scenario lint."""

from __future__ import annotations

import unittest

from tests.lint.filesystem.playwright import test_persona_specs as lint

REL = "roles/web-app-x/files/playwright/test-ldap.js"
HEADER = (
    'const { test, expect } = require("@playwright/test");\n'
    'const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");\n'
)
HELPER = (
    "function skipUnlessLdapLogin() {\n"
    '  skipUnlessServiceEnabled("ldap");\n'
    "}\n"
    "module.exports = { skipUnlessLdapLogin };\n"
)


def _scenarios(text: str, *helpers: str) -> list[lint.Scenario]:
    return lint.scenarios_in(REL, HEADER + text, lint.helper_functions_in(helpers))


def _test(title: str, body: str = "") -> str:
    return (
        f'test("{title}", async ({{ page }}) => {{\n'
        f"{body}\n"
        '  await expect(page).toHaveURL("/");\n'
        "});\n"
    )


def _ungated(text: str, *helpers: str) -> list[str]:
    return [s.title for s in lint.ungated_ldap_scenarios(_scenarios(text, *helpers))]


def _untokened(text: str) -> list[str]:
    return [s.title for s in lint.unpersonified_ldap_scenarios(_scenarios(text))]


class TestLdapGate(unittest.TestCase):
    def test_an_ungated_ldap_login_fails(self) -> None:
        title = "biber: LDAP login and logout"
        self.assertEqual([title], _ungated(_test(title)))

    def test_the_canonical_ldap_gate_passes(self) -> None:
        text = _test("biber: LDAP login", '  skipUnlessServiceEnabled("ldap");')
        self.assertEqual([], _ungated(text))

    def test_a_gate_through_a_helper_module_passes(self) -> None:
        text = _test("administrator: LDAP login", "  shared.skipUnlessLdapLogin();")
        self.assertEqual([], _ungated(text, HELPER))

    def test_a_gate_through_a_local_function_passes(self) -> None:
        text = HELPER + _test("administrator: LDAP login", "  skipUnlessLdapLogin();")
        self.assertEqual([], _ungated(text))

    def test_a_file_level_hook_gate_passes(self) -> None:
        hook = 'test.beforeEach(() => {\n  skipUnlessServiceEnabled("ldap");\n});\n'
        self.assertEqual([], _ungated(hook + _test("biber: LDAP login")))

    def test_a_hook_in_another_describe_grants_nothing(self) -> None:
        text = (
            'test.describe("ldap", () => {\n'
            '  test.beforeEach(() => skipUnlessServiceEnabled("ldap"));\n'
            "});\n" + _test("biber: LDAP login")
        )
        self.assertEqual(["biber: LDAP login"], _ungated(text))

    def test_a_function_of_another_test_module_grants_nothing(self) -> None:
        other = 'exports.register = (shared) => {\n  skipUnlessServiceEnabled("ldap");\n  test("x", () => {});\n};\n'
        text = _test("biber: LDAP login", "  register(page);")
        self.assertEqual(["biber: LDAP login"], _ungated(text, other))

    def test_an_ldap_off_assertion_passes(self) -> None:
        text = _test(
            "administrator: the LDAP plugin stays off",
            '  skipUnlessServiceDisabled("ldap");',
        )
        self.assertEqual([], _ungated(text))

    def test_an_sso_side_probe_without_persona_token_passes(self) -> None:
        text = _test(
            "login methods: with SSO on the LDAP login answers",
            '  skipUnlessServiceEnabled("sso");',
        )
        self.assertEqual([], _ungated(text))

    def test_a_persona_ldap_login_gated_on_sso_fails(self) -> None:
        title = "biber: LDAP login"
        self.assertEqual(
            [title], _ungated(_test(title, '  skipUnlessServiceEnabled("sso");'))
        )

    def test_a_product_name_is_no_ldap_title(self) -> None:
        self.assertEqual(
            [], _ungated(_test("guest: phpLDAPadmin front page is served"))
        )

    def test_a_gate_inside_a_comment_grants_nothing(self) -> None:
        title = "biber: LDAP login"
        text = _test(title, '  // skipUnlessServiceEnabled("ldap");')
        self.assertEqual([title], _ungated(text))


class TestLdapPersonaToken(unittest.TestCase):
    def test_an_ldap_scenario_naming_biber_without_token_fails(self) -> None:
        title = "biber profile-edit form locks the mapped fields"
        text = _test(title, '  skipUnlessServiceEnabled("ldap");')
        self.assertEqual([title], _untokened(text))

    def test_a_persona_token_passes(self) -> None:
        text = _test(
            "biber: profile-edit form locks the mapped fields",
            '  skipUnlessServiceEnabled("ldap");',
        )
        self.assertEqual([], _untokened(text))

    def test_a_persona_placeholder_passes(self) -> None:
        text = (
            "for (const persona of PERSONAS) {\n"
            "  test(`${persona.label}: sign-in binds against the directory`, async ({ page }) => {\n"
            '    skipUnlessServiceEnabled("ldap");\n'
            "  });\n"
            "}\n"
        )
        self.assertEqual([], _untokened(text))

    def test_a_probe_naming_no_persona_passes(self) -> None:
        text = _test(
            "userpass: the method is absent while ldap carries the sign-in",
            '  skipUnlessServiceEnabled("ldap");',
        )
        self.assertEqual([], _untokened(text))


def _combined(text: str, *helpers: str) -> list[str]:
    return [
        s.title for s in lint.combined_sso_ldap_scenarios(_scenarios(text, *helpers))
    ]


class TestSeparateSsoAndLdapBodies(unittest.TestCase):
    def test_a_test_gated_on_sso_and_ldap_fails(self) -> None:
        title = "administrator: LDAP login behind the SSO gate"
        body = '  skipUnlessServiceEnabled("sso");\n  skipUnlessServiceEnabled("ldap");'
        self.assertEqual([title], _combined(_test(title, body)))

    def test_ldap_on_with_sso_off_passes(self) -> None:
        body = (
            '  skipUnlessServiceEnabled("ldap");\n  skipUnlessServiceDisabled("sso");'
        )
        self.assertEqual([], _combined(_test("biber: LDAP login", body)))

    def test_an_sso_gate_through_a_helper_fails(self) -> None:
        helper = (
            "function skipUnlessSsoLogin() {\n"
            '  skipUnlessServiceEnabled("sso");\n'
            "}\n"
            "module.exports = { skipUnlessSsoLogin };\n"
        )
        title = "biber: LDAP login"
        body = '  shared.skipUnlessSsoLogin();\n  skipUnlessServiceEnabled("ldap");'
        self.assertEqual([title], _combined(_test(title, body), helper))

    def test_an_sso_gate_through_a_hook_fails(self) -> None:
        hook = 'test.beforeEach(() => {\n  skipUnlessServiceEnabled("sso");\n});\n'
        title = "biber: LDAP login"
        text = hook + _test(title, '  skipUnlessServiceEnabled("ldap");')
        self.assertEqual([title], _combined(text))

    def test_a_runtime_front_door_passes(self) -> None:
        body = (
            '  skipUnlessServiceEnabled("ldap");\n'
            '  const login = isServiceEnabled("sso") ? loginBehindGate : loginDirect;\n'
            "  await login(page);"
        )
        self.assertEqual([], _combined(_test("administrator: LDAP login", body)))

    def test_separate_sso_and_ldap_tests_pass(self) -> None:
        text = _test(
            "administrator: SSO login", '  skipUnlessServiceEnabled("sso");'
        ) + _test("administrator: LDAP login", '  skipUnlessServiceEnabled("ldap");')
        self.assertEqual([], _combined(text))


class TestRoleCoverage(unittest.TestCase):
    def test_declares_ldap(self) -> None:
        dynamic = "{{ 'svc-db-openldap' in group_names }}"
        self.assertTrue(lint.declares_ldap({"ldap": {"enabled": dynamic}}))
        self.assertTrue(lint.declares_ldap({"ldap": {"enabled": True}}))
        self.assertFalse(lint.declares_ldap({"ldap": {"enabled": False}}))
        self.assertFalse(lint.declares_ldap({"sso": {"enabled": True}}))

    def test_ldap_coverage_section(self) -> None:
        readme = "# Role\n\n## LDAP coverage\n\nbiber follows.\n\n## Next\n\nother\n"
        self.assertEqual("\n\nbiber follows.\n\n", lint.ldap_coverage_section(readme))
        self.assertIsNone(lint.ldap_coverage_section("# Role\n\n## Features\n"))

    def test_an_admin_only_ldap_role_lacks_biber(self) -> None:
        admin = _test(
            "administrator: LDAP login", '  skipUnlessServiceEnabled("ldap");'
        )
        biber = _test("biber: LDAP login", '  skipUnlessServiceEnabled("ldap");')
        self.assertTrue(lint.lacks_biber_ldap_scenario(_scenarios(admin)))
        self.assertFalse(lint.lacks_biber_ldap_scenario(_scenarios(admin + biber)))

    def test_ldap_persona_gap(self) -> None:
        gate = '  skipUnlessServiceEnabled("ldap");'
        admin = _test("administrator: LDAP login", gate)
        biber = _test("biber: LDAP login", gate)
        probe = _test(
            "userpass: the method is absent while ldap carries the sign-in", gate
        )
        guest = _test("guest: the LDAP login refuses an unknown account", gate)
        placeholder = (
            "for (const persona of PERSONAS) {\n"
            "  test(`${persona.label}: LDAP login`, async ({ page }) => {\n"
            f"  {gate}\n"
            "  });\n"
            "}\n"
        )
        self.assertEqual("biber", lint.ldap_persona_gap(_scenarios(admin + probe)))
        self.assertEqual("administrator", lint.ldap_persona_gap(_scenarios(biber)))
        self.assertEqual("persona", lint.ldap_persona_gap(_scenarios(probe + guest)))
        self.assertIsNone(lint.ldap_persona_gap(_scenarios(admin + biber)))
        self.assertIsNone(lint.ldap_persona_gap(_scenarios(placeholder)))
        self.assertIsNone(lint.ldap_persona_gap(_scenarios(_test("biber: SSO login"))))

    def test_an_sso_gated_administrator_does_not_cover_ldap(self) -> None:
        admin = _test("administrator: SSO login", '  skipUnlessServiceEnabled("sso");')
        biber = _test("biber: LDAP login", '  skipUnlessServiceEnabled("ldap");')
        self.assertEqual(
            "administrator", lint.ldap_persona_gap(_scenarios(admin + biber))
        )


if __name__ == "__main__":
    unittest.main()
