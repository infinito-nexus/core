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

PHP_SOURCE = (
    "Shared PHP hardening ini and PHP-FPM pool drop-in that PHP services of "
    "compose and swarm stacks mount as configs"
)
STORAGE_SOURCE = "Shared storage for backups and media files"
STORAGE_RENDERINGS = {
    "de": "Gemeinsamer Speicher für Sicherungen und Mediendateien",
    "hi": "बैकअप और मीडिया फ़ाइलों के लिए साझा भंडारण",
    "ar": "تخزين مشترك للنسخ الاحتياطية وملفات الوسائط",
    "ur": "بیک اپ اور میڈیا فائلوں کے لیے مشترکہ اسٹوریج",
    "vi": "Bộ nhớ dùng chung cho bản sao lưu và tệp đa phương tiện",
    "ja": "バックアップとメディアファイル用の共有ストレージ",
}


class TestSoundRenderingsPass(unittest.TestCase):
    """A sound rendering passes every criterion, whatever script its language writes."""

    def test_every_sound_rendering_is_kept(self) -> None:
        for language, rendering in STORAGE_RENDERINGS.items():
            with self.subTest(language=language):
                self.assertEqual(reason(STORAGE_SOURCE, rendering, language), "")


class TestAddedLines(unittest.TestCase):
    """A translation breaking lines its source does not break carries text besides the rendering."""

    def test_a_preamble_line_naming_the_task_is_condemned(self) -> None:
        answer = (
            "Translation of the text to Vietnamese:\n\n"
            "Đã chia sẻ PHP hardening và pool drop-in PHP dịch vụ của tài nguyên "
            "compose và tài nguyên swarm mounts làm cấu hình"
        )
        self.assertEqual(reason(PHP_SOURCE, answer, "vi"), "added-line")

    def test_a_trailing_note_is_condemned(self) -> None:
        answer = 'Outils\n---\n\nNote: The term "Tools" is translated as "Outils".'
        self.assertEqual(reason("Tools", answer, "bi"), "added-line")

    def test_a_label_on_a_line_of_its_own_is_condemned(self) -> None:
        self.assertEqual(reason("Added:", "Added:\n\nPřidáno:", "cs"), "added-line")

    def test_a_line_break_the_source_carries_is_kept(self) -> None:
        self.assertEqual(
            reason("First line\nSecond line", "Erste Zeile\nZweite Zeile", "de"), ""
        )


class TestLetterDigitTokens(unittest.TestCase):
    """A name that carries its version digit is one token the translation must keep whole."""

    SOURCE: ClassVar[str] = "S3-compatible object storage shared by the roles"

    def test_a_token_torn_from_its_digit_is_condemned(self) -> None:
        answer = "Amazon S ilə uyğun obyekt saxlama, rollar arasında paylaşılan"
        self.assertEqual(reason(self.SOURCE, answer, "az"), "protected-span")

    def test_a_token_moved_onto_another_word_is_condemned(self) -> None:
        answer = "Distribuid3-compatible obyekt stora agaaniin share"
        self.assertEqual(reason(self.SOURCE, answer, "aa"), "protected-span")

    def test_a_rendering_keeping_the_token_is_kept(self) -> None:
        answer = "S3-kompatibler Objektspeicher, den die Rollen teilen"
        self.assertEqual(reason(self.SOURCE, answer, "de"), "")


class TestWrongNonLatinScript(unittest.TestCase):
    """A language written in a non-Latin script came back in another non-Latin one."""

    def test_urdu_written_in_devanagari_is_condemned(self) -> None:
        answer = (
            "Shared PHP हथियार रोजन और PHP-FPM प्लून जो PHP सेवाओं ऑस्टर्म "
            "यूडियोक्सस चालक क्रिप्टोग्राफी इकाइ मount करते हैं"
        )
        self.assertEqual(reason(PHP_SOURCE, answer, "ur"), "wrong-script")

    def test_hindi_written_in_devanagari_is_kept(self) -> None:
        answer = (
            "साझा PHP सख्त ini और PHP-FPM पूल ड्रॉप-इन कि PHP सेवाओं की रचना और "
            "swarm स्टैक विन्यास के रूप में माउंट"
        )
        self.assertEqual(reason(PHP_SOURCE, answer, "hi"), "")

    def test_amharic_answered_in_armenian_is_condemned(self) -> None:
        self.assertEqual(
            reason("AI Services", "AI լացոցություներ", "am"), "wrong-script"
        )

    def test_a_word_in_a_script_the_source_lacks_outweighing_the_own_one_is_condemned(
        self,
    ) -> None:
        self.assertEqual(
            reason(
                "Switch the interface to Russian",
                "インターフェースを Русский に切り替える",
                "ja",
            ),
            "wrong-script",
        )

    def test_a_script_the_source_carries_is_not_counted(self) -> None:
        self.assertEqual(
            reason(
                "Switch the interface to Русский",
                "インターフェースを Русский に切り替える",
                "ja",
            ),
            "",
        )

    def test_a_lone_letter_of_another_script_is_not_counted(self) -> None:
        self.assertEqual(reason("alpha", "α", "zh"), "")
        self.assertEqual(
            reason("Gated to alpha and beta lifecycles", "仅限 α 和 β 生命周期", "zh"),
            "",
        )

    def test_a_latin_script_target_is_not_judged_by_this_rule(self) -> None:
        self.assertEqual(reason("Applications", "Anwendungen", "de"), "")


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
