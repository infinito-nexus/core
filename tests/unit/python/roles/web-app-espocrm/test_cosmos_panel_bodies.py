from __future__ import annotations

import unittest

from tests.lint.filesystem.test_cosmos_sheets import ROLES, SHEET, sky_colors
from utils.cache.files import read_text

ESPOCRM_SHEET = ROLES / "web-app-espocrm" / SHEET
PANEL_BODY = ".panel-body"
DESIGN_TEXT = "var(--design-text)"
COSMOS_TEXT = "var(--cosmos-text)"
PANEL_RULE = (
    "{{ COSMOS_SKY_SELECTOR }} .panel-body {\n  color: var(--design-text);\n}\n"
)


class TestEspocrmCosmosPanelBodies(unittest.TestCase):
    def setUp(self) -> None:
        self.sheet = read_text(str(ESPOCRM_SHEET))

    def test_the_sky_turns_the_page_text_to_the_cosmos_text(self) -> None:
        self.assertIn(COSMOS_TEXT, sky_colors(self.sheet, "body"))

    def test_the_panel_bodies_take_the_design_text_back(self) -> None:
        self.assertEqual(
            sky_colors(self.sheet, PANEL_BODY),
            [DESIGN_TEXT],
            "the panel bodies, the login form among them, sit on "
            "--design-surface-2, so text inherited from the sky's "
            "--cosmos-text on body reaches contrast 1.01",
        )

    def test_a_sheet_without_the_panel_rule_is_caught(self) -> None:
        self.assertIn(PANEL_RULE, self.sheet)
        stripped = self.sheet.replace(PANEL_RULE, "")
        self.assertIn(COSMOS_TEXT, sky_colors(stripped, "body"))
        self.assertEqual(sky_colors(stripped, PANEL_BODY), [])


if __name__ == "__main__":
    unittest.main()
