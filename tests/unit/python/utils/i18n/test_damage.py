"""Unit tests for the criterion that condemns an answer carrying its source.

The shape is one the gateway produced across twenty languages: the English
source, a markdown rule, then a rendering. Every other criterion passed it,
because the rendering keeps the spans and the names and the separator is made
of characters the markup comparison does not count.
"""

from __future__ import annotations

import unittest
from typing import ClassVar

from utils.i18n.damage import reason


class TestEchoAndContinue(unittest.TestCase):
    """A translation holding its whole source is the server failing, not translating."""

    SOURCE: ClassVar[str] = (
        "Corporate design injection for NGINX-served apps, unifying light and "
        "dark theming from OKLCH design tokens"
    )
    RENDERING: ClassVar[str] = (
        "Corporate-Design-Injection für NGINX-bediente Anwendungen, vereinheitlicht "
        "helles und dunkles Theming aus OKLCH-Design-Tokens"
    )

    def test_an_answer_that_prepends_its_source_is_condemned(self) -> None:
        answer = f"{self.SOURCE}\n---\n\n{self.RENDERING}"
        self.assertEqual(reason(self.SOURCE, answer, "de"), "echo")

    def test_an_answer_that_appends_its_source_is_condemned(self) -> None:
        answer = f"{self.RENDERING}\n\n{self.SOURCE}"
        self.assertEqual(reason(self.SOURCE, answer, "de"), "echo")

    def test_a_rendering_that_drops_the_source_is_kept(self) -> None:
        self.assertEqual(reason(self.SOURCE, self.RENDERING, "de"), "")

    def test_a_short_source_may_live_inside_a_longer_rendering(self) -> None:
        source = "Mail"
        self.assertEqual(reason(source, "Mail-Konto des Benutzers", "de"), "")


if __name__ == "__main__":
    unittest.main()
