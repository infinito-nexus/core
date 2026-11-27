from __future__ import annotations

import unittest

from tests.lint.filesystem.test_cosmos_sheets import render, rules, selectors
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text

SHEET = PROJECT_ROOT / "roles" / "web-app-docs" / "templates" / "cosmos.css.j2"
INLINE_CODE = "code:not(pre code)"
DESIGN_TEXT = "var(--design-text)"
COSMOS_TEXT = "var(--cosmos-text)"


def sky_colors(text: str, subject: str) -> list[str]:
    """
    Args:
        text: a cosmos sheet template.
        subject: the trailing selector part to match.

    Returns:
        The color of every rule that applies under the sky outside the
        legible-top band and selects ``subject``.
    """
    sky, top = selectors()
    return [
        declared["color"]
        for chosen, declared in rules(render(text, sky, top))
        for selector in chosen
        if "color" in declared
        and selector.startswith(sky)
        and not selector.startswith(top)
        and selector.endswith(subject)
    ]


class TestDocsCosmosInlineCode(unittest.TestCase):
    def test_the_sky_turns_the_page_text_to_the_cosmos_text(self) -> None:
        self.assertIn(COSMOS_TEXT, sky_colors(read_text(str(SHEET)), "body"))

    def test_inline_code_keeps_the_design_text_on_its_own_surface(self) -> None:
        self.assertEqual(sky_colors(read_text(str(SHEET)), INLINE_CODE), [DESIGN_TEXT])


if __name__ == "__main__":
    unittest.main()
