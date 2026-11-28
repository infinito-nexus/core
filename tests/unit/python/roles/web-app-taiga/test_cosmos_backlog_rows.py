from __future__ import annotations

import unittest

from tests.lint.filesystem.test_cosmos_sheets import ROLES, SHEET, sky_colors
from utils.cache.files import read_text

TAIGA_SHEET = ROLES / "web-app-taiga" / SHEET
BACKLOG_ROW = ".backlog-table-body .row"
DESIGN_TEXT = "var(--design-text)"
COSMOS_TEXT = "var(--cosmos-text)"
ROW_RULE = (
    "{{ COSMOS_SKY_SELECTOR }} .backlog-table-body .row {\n"
    "  color: var(--design-text);\n}\n"
)


class TestTaigaCosmosBacklogRows(unittest.TestCase):
    def setUp(self) -> None:
        self.sheet = read_text(str(TAIGA_SHEET))

    def test_the_sky_turns_the_app_text_to_the_cosmos_text(self) -> None:
        self.assertIn(COSMOS_TEXT, sky_colors(self.sheet, ".master"))

    def test_the_backlog_rows_take_the_design_text_back(self) -> None:
        self.assertEqual(
            sky_colors(self.sheet, BACKLOG_ROW),
            [DESIGN_TEXT],
            "the backlog rows sit on --design-surface-2, so text inherited "
            "from the sky's --cosmos-text on .master reaches contrast 1.01",
        )

    def test_a_sheet_without_the_row_rule_is_caught(self) -> None:
        self.assertIn(ROW_RULE, self.sheet)
        stripped = self.sheet.replace(ROW_RULE, "")
        self.assertIn(COSMOS_TEXT, sky_colors(stripped, ".master"))
        self.assertEqual(sky_colors(stripped, BACKLOG_ROW), [])


if __name__ == "__main__":
    unittest.main()
