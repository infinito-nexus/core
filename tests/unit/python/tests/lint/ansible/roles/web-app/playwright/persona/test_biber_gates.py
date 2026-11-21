from __future__ import annotations

import unittest

from tests.lint.filesystem.playwright import test_persona_specs as lint

REL = "roles/web-app-x/files/playwright/test-rbac.js"
OTHER = "roles/web-app-x/files/playwright/test-login.js"
HEADER = 'const { test, expect } = require("@playwright/test");\n'
SSO = '  skipUnlessServiceEnabled("sso");'
LDAP = '  skipUnlessServiceEnabled("ldap");'
LDAP_ONLY = '  skipUnlessServiceEnabled("ldap");\n  skipUnlessServiceDisabled("sso");'


def _test(title: str, body: str = "") -> str:
    return (
        f'test("{title}", async ({{ page }}) => {{\n'
        f"{body}\n"
        '  await expect(page).toHaveURL("/");\n'
        "});\n"
    )


def _offenders(modules: dict[str, str], *helpers: str) -> list[tuple[str, str]]:
    functions = lint.helper_functions_in(helpers)
    items = [
        item
        for rel, text in modules.items()
        for item in lint.persona_tests_in(rel, HEADER + text, functions)
    ]
    return [(s.title, reason) for s, reason in lint.biber_gate_offenders(items)]


class TestBiberGates(unittest.TestCase):
    def test_an_ungated_biber_scenario_fails(self) -> None:
        title = "biber: login and logout"
        self.assertEqual([(title, "ungated")], _offenders({REL: _test(title)}))

    def test_an_sso_gated_biber_scenario_passes(self) -> None:
        self.assertEqual([], _offenders({REL: _test("biber: login", SSO)}))

    def test_a_disabled_gate_alone_is_ungated(self) -> None:
        title = "biber: login while SSO is off"
        body = '  skipUnlessServiceDisabled("sso");'
        self.assertEqual([(title, "ungated")], _offenders({REL: _test(title, body)}))

    def test_a_gate_inside_a_comment_grants_nothing(self) -> None:
        title = "biber: login"
        body = '  // skipUnlessServiceEnabled("sso");'
        self.assertEqual([(title, "ungated")], _offenders({REL: _test(title, body)}))

    def test_the_shared_persona_flow_is_exempt(self) -> None:
        text = _test("biber: app → universal logout", "  await runBiberFlow(page);")
        self.assertEqual([], _offenders({REL: text}))

    def test_the_shared_persona_flow_through_a_helper_is_exempt(self) -> None:
        helper = (
            "function journey(page) {\n"
            "  return runBiberFlow(page);\n"
            "}\n"
            "module.exports = { journey };\n"
        )
        text = _test("biber: journey", "  await shared.journey(page);")
        self.assertEqual([], _offenders({REL: text}, helper))

    def test_a_gate_through_a_helper_counts(self) -> None:
        helper = (
            "function skipUnlessSso() {\n"
            '  skipUnlessServiceEnabled("sso");\n'
            "}\n"
            "module.exports = { skipUnlessSso };\n"
        )
        text = _test("biber: login", "  shared.skipUnlessSso();")
        self.assertEqual([], _offenders({REL: text}, helper))

    def test_gates_differing_from_the_module_administrator_fail(self) -> None:
        title = "biber: LDAP login"
        text = _test("administrator: LDAP login", LDAP_ONLY) + _test(title, LDAP)
        self.assertEqual([(title, "mismatch")], _offenders({REL: text}))

    def test_gates_equal_to_the_module_administrator_pass(self) -> None:
        text = _test("administrator: LDAP login", LDAP_ONLY) + _test(
            "biber: LDAP login", LDAP_ONLY
        )
        self.assertEqual([], _offenders({REL: text}))

    def test_an_administrator_on_another_service_does_not_match(self) -> None:
        text = _test("administrator: LDAP login", LDAP_ONLY) + _test(
            "biber: the proxy refuses biber", SSO
        )
        self.assertEqual([], _offenders({REL: text}))

    def test_an_administrator_of_another_module_does_not_match(self) -> None:
        modules = {
            OTHER: _test("administrator: LDAP import", LDAP),
            REL: _test("biber: LDAP login", LDAP_ONLY),
        }
        self.assertEqual([], _offenders(modules))

    def test_one_matching_administrator_is_enough(self) -> None:
        stacked = SSO + '\n  skipUnlessServiceDisabled("ldap");'
        text = (
            _test("administrator: SSO login", SSO)
            + _test("administrator: SSO login without the directory", stacked)
            + _test("biber: SSO login", SSO)
        )
        self.assertEqual([], _offenders({REL: text}))


if __name__ == "__main__":
    unittest.main()
