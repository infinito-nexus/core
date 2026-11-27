from __future__ import annotations

import unittest

from tests.lint.filesystem.test_cosmos_sheets import ROLES, SHEET, sky_colors
from utils.cache.files import read_text

GITLAB_SHEET = ROLES / "web-app-gitlab" / SHEET
CONTENT_PANELS = ".content-panels"
DESIGN_TEXT = "var(--design-text)"
COSMOS_TEXT = "var(--cosmos-text)"
PANEL_RULE = (
    "{{ COSMOS_SKY_SELECTOR }} .content-panels {\n  color: var(--design-text);\n}\n"
)


class TestGitlabCosmosContentPanels(unittest.TestCase):
    def setUp(self) -> None:
        self.sheet = read_text(str(GITLAB_SHEET))

    def test_the_sky_turns_the_page_text_to_the_cosmos_text(self) -> None:
        self.assertIn(COSMOS_TEXT, sky_colors(self.sheet, "body"))

    def test_the_content_panels_take_the_design_text_back(self) -> None:
        self.assertEqual(
            sky_colors(self.sheet, CONTENT_PANELS),
            [DESIGN_TEXT],
            "--cosmos-text follows the sky, not the color scheme, so the "
            "design surface of the content panels needs --design-text or "
            "inherited text such as the admin dashboard dividers stays black "
            "on the dark surface",
        )

    def test_a_sheet_without_the_panel_rule_is_caught(self) -> None:
        self.assertIn(PANEL_RULE, self.sheet)
        stripped = self.sheet.replace(PANEL_RULE, "")
        self.assertIn(COSMOS_TEXT, sky_colors(stripped, "body"))
        self.assertEqual(sky_colors(stripped, CONTENT_PANELS), [])


if __name__ == "__main__":
    unittest.main()
