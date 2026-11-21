from __future__ import annotations

import unittest

from tests.lint.filesystem.playwright import test_persona_specs as lint

REL = "roles/web-app-x/files/playwright/test-biber.js"
HEADER = 'const { test, expect } = require("@playwright/test");\n'
REFUSED = "  expect(response.status()).toBe(403);"
LANDED = "  await expect(page).toHaveURL(/\\/dashboard/);"
ADMIN_MENU = '  await expect(page.locator("#admin-menu")).toBeVisible();'


def _test(title: str, *lines: str) -> str:
    body = "\n".join(lines)
    return f'test("{title}", async ({{ page }}) => {{\n{body}\n}});\n'


def _offenders(text: str, *helpers: str) -> list[tuple[str, str]]:
    functions = lint.helper_functions_in(helpers)
    items = lint.persona_tests_in(REL, HEADER + text, functions)
    return [(s.title, reason) for s, reason in lint.end_surface_offenders(items)]


class TestEndSurface(unittest.TestCase):
    def test_a_role_whose_biber_tests_prove_no_page_fails(self) -> None:
        title = "biber: the API refuses biber"
        self.assertEqual([(title, "no-surface")], _offenders(_test(title, REFUSED)))

    def test_a_url_assertion_passes(self) -> None:
        self.assertEqual([], _offenders(_test("biber: lands", LANDED)))

    def test_one_surfaced_biber_test_covers_the_role(self) -> None:
        text = _test("biber: refused", REFUSED) + _test("biber: lands", LANDED)
        self.assertEqual([], _offenders(text))

    def test_the_shared_persona_flow_covers_the_role(self) -> None:
        text = _test(
            "biber: app → universal logout", "  await runBiberFlow(page);"
        ) + _test("biber: refused", REFUSED)
        self.assertEqual([], _offenders(text))

    def test_a_negated_surface_proves_nothing(self) -> None:
        title = "biber: no menu"
        line = '  await expect(page.locator("#menu")).not.toBeVisible();'
        self.assertEqual([(title, "no-surface")], _offenders(_test(title, line)))

    def test_an_empty_count_proves_nothing(self) -> None:
        title = "biber: no rows"
        line = '  await expect(page.locator("tr")).toHaveCount(0);'
        self.assertEqual([(title, "no-surface")], _offenders(_test(title, line)))

    def test_a_count_of_rendered_elements_passes(self) -> None:
        line = '  await expect(page.locator("tr")).toHaveCount(2);'
        self.assertEqual([], _offenders(_test("biber: two rows", line)))

    def test_a_value_matcher_on_the_page_url_passes(self) -> None:
        line = '  expect(new URL(page.url()).pathname).toBe("/oauth2/callback");'
        self.assertEqual([], _offenders(_test("biber: refused at the gate", line)))

    def test_a_polled_page_url_passes(self) -> None:
        line = '  await expect.poll(() => page.url()).toContain("/apps");'
        self.assertEqual([], _offenders(_test("biber: lands", line)))

    def test_a_computed_flag_proves_nothing(self) -> None:
        title = "biber: denied"
        line = "  expect(forbidden || !onAppHost).toBe(true);"
        self.assertEqual([(title, "no-surface")], _offenders(_test(title, line)))

    def test_a_surface_inside_a_comment_proves_nothing(self) -> None:
        title = "biber: refused"
        text = _test(title, "  // await expect(page).toHaveURL(/dashboard/);", REFUSED)
        self.assertEqual([(title, "no-surface")], _offenders(text))

    def test_a_surface_reached_through_a_helper_passes(self) -> None:
        helper = (
            "async function landOnDashboard(page) {\n"
            "  await expect(page).toHaveURL(/dashboard/);\n"
            "}\n"
            "module.exports = { landOnDashboard };\n"
        )
        text = _test("biber: lands", "  await shared.landOnDashboard(page);")
        self.assertEqual([], _offenders(text, helper))

    def test_a_role_without_biber_tests_is_not_judged(self) -> None:
        self.assertEqual([], _offenders(_test("administrator: refused", REFUSED)))


class TestAdminUi(unittest.TestCase):
    def test_an_admin_element_seen_by_biber_fails(self) -> None:
        title = "biber: lands"
        text = _test(title, LANDED, ADMIN_MENU)
        self.assertEqual([(title, "admin-ui")], _offenders(text))

    def test_an_admin_url_reached_by_biber_fails(self) -> None:
        title = "biber: lands on the admin area"
        line = "  await expect(page).toHaveURL(/\\/admin\\//);"
        self.assertEqual([(title, "admin-ui")], _offenders(_test(title, line)))

    def test_the_shared_persona_flow_is_judged_too(self) -> None:
        title = "biber: app → universal logout"
        text = _test(title, "  await runBiberFlow(page);", ADMIN_MENU)
        self.assertEqual([(title, "admin-ui")], _offenders(text))

    def test_an_absent_admin_element_passes(self) -> None:
        line = '  await expect(page.locator(".admin-panel")).toHaveCount(0);'
        self.assertEqual([], _offenders(_test("biber: lands", LANDED, line)))

    def test_a_hidden_admin_element_passes(self) -> None:
        line = '  await expect(page.locator("#admin-menu")).not.toBeVisible();'
        self.assertEqual([], _offenders(_test("biber: lands", LANDED, line)))

    def test_the_wordpress_admin_bar_passes(self) -> None:
        line = '  await expect(page.locator("#wp-admin-bar-my-account")).toBeVisible();'
        self.assertEqual([], _offenders(_test("biber: lands", line)))

    def test_an_admin_word_in_the_message_passes(self) -> None:
        line = (
            '  await expect(page, "biber must never reach the admin panel")'
            ".toHaveURL(/\\/dashboard/);"
        )
        self.assertEqual([], _offenders(_test("biber: lands", line)))

    def test_a_second_session_may_assert_admin_ui(self) -> None:
        lines = (
            "  const adminPage = await browser.newPage();",
            '  await expect(adminPage.locator("#admin-menu")).toBeVisible();',
            LANDED,
        )
        self.assertEqual([], _offenders(_test("biber: invited by the admin", *lines)))

    def test_a_biber_promoted_to_the_administrator_group_may_assert_admin_ui(
        self,
    ) -> None:
        lines = (
            "  await withBiberInGroup(administratorGroupPath, async () => {",
            ADMIN_MENU,
            "  });",
        )
        self.assertEqual([], _offenders(_test("biber: promoted", *lines)))


if __name__ == "__main__":
    unittest.main()
