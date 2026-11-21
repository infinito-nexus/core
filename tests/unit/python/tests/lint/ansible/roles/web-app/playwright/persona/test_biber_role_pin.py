from __future__ import annotations

import unittest

from tests.lint.filesystem.playwright import test_persona_specs as lint

REL = "roles/web-app-x/files/playwright/test-biber.js"
HEADER = 'const { test, expect } = require("@playwright/test");\n'
RBAC = {"roles": {"administrator": {}, "editor": {}, "mcp": {}}}
LANDED = "  await expect(page).toHaveURL(/\\/dashboard/);"
FLAG = "# X\n\n## Biber coverage\n\nThe biber check is bare; a follow-up pins editor.\n"


def _test(title: str, *lines: str) -> str:
    body = "\n".join(lines)
    return f'test("{title}", async ({{ page }}) => {{\n{body}\n}});\n'


def _gap(text: str, rbac: object = RBAC, readme: str = "") -> bool:
    items = lint.persona_tests_in(REL, HEADER + text, {})
    return lint.role_pin_gap(items, rbac, readme)


class TestApplicationRoles(unittest.TestCase):
    def test_administrator_and_mcp_are_no_application_role(self) -> None:
        self.assertEqual(frozenset({"editor"}), lint.application_roles(RBAC))

    def test_a_missing_contract_offers_no_role(self) -> None:
        self.assertEqual(frozenset(), lint.application_roles({}))
        self.assertEqual(frozenset(), lint.application_roles(None))


class TestRolePinGap(unittest.TestCase):
    def test_a_bare_post_login_check_fails(self) -> None:
        self.assertTrue(_gap(_test("biber: lands", LANDED)))

    def test_the_shared_persona_flow_alone_fails(self) -> None:
        self.assertTrue(
            _gap(_test("biber: app → logout", "  await runBiberFlow(page);"))
        )

    def test_a_readme_flag_passes(self) -> None:
        self.assertFalse(_gap(_test("biber: lands", LANDED), readme=FLAG))

    def test_an_empty_readme_section_does_not_flag(self) -> None:
        readme = "# X\n\n## Biber coverage\n\n## Next\n"
        self.assertTrue(_gap(_test("biber: lands", LANDED), readme=readme))

    def test_a_role_scoped_element_pins_the_role(self) -> None:
        line = '  await expect(page.getByRole("button", { name: "editor tools" })).toBeVisible();'
        self.assertFalse(_gap(_test("biber: lands", LANDED, line)))

    def test_a_role_name_inside_a_longer_word_does_not_pin(self) -> None:
        line = '  await expect(page.locator(".editorial")).toBeVisible();'
        self.assertTrue(_gap(_test("biber: lands", LANDED, line)))

    def test_an_absent_admin_element_pins_the_role(self) -> None:
        line = '  await expect(page.locator("#admin-menu")).toHaveCount(0);'
        self.assertFalse(_gap(_test("biber: lands", LANDED, line)))

    def test_an_absent_admin_constant_pins_the_role(self) -> None:
        line = "  await expect(page.locator(ADMIN_SUMMARY)).not.toBeVisible();"
        self.assertFalse(_gap(_test("biber: lands", LANDED, line)))

    def test_a_refused_admin_route_pins_the_role(self) -> None:
        line = "  expect(response.status()).toBe(403);"
        self.assertFalse(_gap(_test("biber: the admin panel refuses biber", line)))

    def test_a_refusal_unrelated_to_admin_does_not_pin(self) -> None:
        line = "  expect(response.status()).toBe(403);"
        self.assertTrue(_gap(_test("biber: the upload is refused", LANDED, line)))

    def test_a_generic_negation_does_not_pin(self) -> None:
        line = '  await expect.poll(() => page.url()).not.toContain("/auth");'
        self.assertTrue(_gap(_test("biber: leaves the sign-in", line)))

    def test_a_visible_admin_element_does_not_pin(self) -> None:
        line = '  await expect(page.locator("#admin-menu")).toBeVisible();'
        self.assertTrue(_gap(_test("biber: lands", LANDED, line)))

    def test_an_administrator_scenario_does_not_pin_for_biber(self) -> None:
        line = '  await expect(page.locator("#admin-menu")).toHaveCount(0);'
        text = _test("biber: lands", LANDED) + _test("administrator: lands", line)
        self.assertTrue(_gap(text))

    def test_a_contract_without_an_application_role_is_out_of_scope(self) -> None:
        rbac = {"roles": {"administrator": {}, "mcp": {}}}
        self.assertFalse(_gap(_test("biber: lands", LANDED), rbac=rbac))

    def test_a_role_without_biber_tests_is_out_of_scope(self) -> None:
        self.assertFalse(_gap(_test("administrator: lands", LANDED)))


if __name__ == "__main__":
    unittest.main()
