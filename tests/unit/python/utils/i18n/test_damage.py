"""Unit tests for the criteria that condemn an answer carrying its source or
coming back in the wrong script.

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


class TestWrongScript(unittest.TestCase):
    """A language written in another script came back in Latin letters.

    The catalogs are mostly one- to four-word labels, and a six-word floor
    once stood in front of this criterion, so it never fired on them: a whole
    run filled Belarusian with Polish and Abkhaz with Spanish while every
    criterion passed.
    """

    def test_a_one_word_answer_in_the_wrong_script_is_condemned(self) -> None:
        self.assertEqual(reason("Applications", "Aplikacje", "be"), "untranslated")

    def test_a_label_answered_in_another_language_is_condemned(self) -> None:
        self.assertEqual(reason("Communication", "Comunicación", "ab"), "untranslated")

    def test_an_answer_in_the_language_s_own_script_is_kept(self) -> None:
        self.assertEqual(reason("Applications", "Праграмы", "be"), "")

    def test_a_latin_script_target_is_not_judged_by_script(self) -> None:
        self.assertEqual(reason("Applications", "Anwendungen", "de"), "")

    def test_a_translation_without_a_word_is_kept(self) -> None:
        self.assertEqual(reason("Status", "100 %", "be"), "")

    def test_a_separatorless_script_counts_one_word_per_character(self) -> None:
        """Japanese and Chinese write without spaces, so a run-based pattern
        returns the whole sentence as one token, and two Latin product names
        inside it carry that token past a half and the ratio to 1.0."""
        self.assertEqual(
            reason(
                "Runs Playwright in Docker with stable browser settings",
                "安定したブラウザ設定でDockerでPlaywrightを実行",
                "ja",
            ),
            "",
        )
        self.assertEqual(
            reason("Run Playwright in Docker", "在Docker中运行Playwright", "zh"), ""
        )

    def test_a_separatorless_script_answered_in_english_is_still_condemned(
        self,
    ) -> None:
        self.assertEqual(
            reason(
                "Runs Playwright in Docker with stable settings",
                "Runs Playwright in Docker with stable browser settings",
                "ja",
            ),
            "untranslated",
        )


class TestForeignScript(unittest.TestCase):
    """A Latin-script language came back in a script it does not use.

    The model answers a language it cannot write with one it can. Chamorro
    came back in Han because the ISO code ``ch`` reads as Chinese, Turkish in
    Bengali, Avestan in Arabic, and none of it was caught while only the
    non-Latin direction was checked.
    """

    def test_han_in_a_latin_script_catalog_is_condemned(self) -> None:
        self.assertEqual(reason("AI Services", "人工智能服务", "ch"), "foreign-script")

    def test_arabic_in_a_latin_script_catalog_is_condemned(self) -> None:
        self.assertEqual(reason("Sales", "إدارة", "tr"), "foreign-script")

    def test_a_latin_script_answer_is_kept(self) -> None:
        self.assertEqual(reason("Applications", "Anwendungen", "de"), "")

    def test_a_non_latin_target_is_not_judged_by_this_rule(self) -> None:
        self.assertEqual(reason("Applications", "Праграмы", "be"), "")

    def test_a_translation_without_a_word_is_kept(self) -> None:
        self.assertEqual(reason("Status", "100 %", "ch"), "")


if __name__ == "__main__":
    unittest.main()
