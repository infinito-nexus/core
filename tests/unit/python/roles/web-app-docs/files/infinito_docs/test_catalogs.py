"""Unit tests for the language declaration a documented checkout carries."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from infinito_docs.catalogs import translated_languages

CATALOG = """\
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

msgid "Overview"
msgstr "%s"
"""

FUZZY = """\
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

#, fuzzy
msgid "Overview"
msgstr "Aperçu"
"""


class TestTranslatedLanguages(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(prefix="infinito-catalogs-")
        self.src = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _declare(self, body: str) -> None:
        (self.src / "meta").mkdir(parents=True, exist_ok=True)
        (self.src / "meta" / "languages.yml").write_text(body, encoding="utf-8")

    def _catalog(self, code: str, body: str) -> None:
        directory = self.src / "locale" / code / "LC_MESSAGES"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "docs.po").write_text(body, encoding="utf-8")

    def test_a_checkout_without_the_declaration_knows_no_language(self) -> None:
        self.assertEqual(translated_languages(self.src), ({}, []))

    def test_the_native_name_is_read_and_a_missing_one_falls_back_to_the_code(
        self,
    ) -> None:
        self._declare("de:\n  native: Deutsch\nfr:\n")

        known, translated = translated_languages(self.src)

        self.assertEqual(known, {"de": "Deutsch", "fr": "fr"})
        self.assertEqual(translated, [])

    def test_a_declared_language_without_a_catalog_is_not_translated(self) -> None:
        self._declare("de:\n  native: Deutsch\n")

        self.assertEqual(translated_languages(self.src)[1], [])

    def test_one_filled_entry_makes_a_language_translated(self) -> None:
        self._declare("de:\n  native: Deutsch\n")
        self._catalog("de", CATALOG % "Übersicht")

        self.assertEqual(translated_languages(self.src)[1], ["de"])

    def test_an_empty_catalog_does_not_count(self) -> None:
        self._declare("de:\n  native: Deutsch\n")
        self._catalog("de", CATALOG % "")

        self.assertEqual(translated_languages(self.src)[1], [])

    def test_a_fuzzy_entry_does_not_count(self) -> None:
        self._declare("fr:\n  native: Français\n")
        self._catalog("fr", FUZZY)

        self.assertEqual(translated_languages(self.src)[1], [])


if __name__ == "__main__":
    unittest.main()
