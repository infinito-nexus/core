import tempfile
import unittest
from pathlib import Path

from utils.i18n.catalog import (
    build_template,
    merge,
    read_catalog,
    translations,
    write_catalog,
)
from utils.i18n.translate import pending


class TestMerge(unittest.TestCase):
    def test_changed_source_comes_back_empty_for_the_translator(self):
        catalog = merge(build_template([("a", "Hello world")], "core"), None, "de")
        catalog.get("Hello world", context="a").string = "Hallo Welt"

        merged = merge(build_template([("a", "Hello world!")], "core"), catalog, "de")

        message = merged.get("Hello world!", context="a")
        self.assertFalse(message.string)
        self.assertFalse(message.fuzzy)
        self.assertEqual(
            [m.id for m in pending(merged)],
            ["Hello world!"],
            "carrying the old translation over would cost a quadratic search for "
            "a value pending() hands straight back to the translator",
        )

    def test_removed_source_disappears(self):
        catalog = merge(
            build_template([("a", "Keep"), ("b", "Drop")], "core"), None, "de"
        )
        catalog.get("Drop", context="b").string = "Weg"

        merged = merge(build_template([("a", "Keep")], "core"), catalog, "de")

        self.assertIsNone(merged.get("Drop", context="b"))
        self.assertEqual(len(merged), 1)

    def test_same_text_in_two_contexts_stays_two_entries(self):
        catalog = merge(
            build_template(
                [("role:x:description", "Wiki"), ("menu:Wiki:title", "Wiki")], "core"
            ),
            None,
            "de",
        )

        self.assertEqual(len(catalog), 2)


class TestWrite(unittest.TestCase):
    def test_rewriting_unchanged_catalog_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "de" / "LC_MESSAGES" / "core.po"
            template = build_template([("a", "Hello"), ("b", "World")], "core")

            self.assertTrue(write_catalog(path, merge(template, None, "de")))
            with path.open("rb") as handle:
                first = handle.read()
            self.assertFalse(
                write_catalog(path, merge(template, read_catalog(path), "de"))
            )

            with path.open("rb") as handle:
                self.assertEqual(handle.read(), first)


class TestTranslations(unittest.TestCase):
    def test_every_written_catalog_names_the_author_and_no_placeholder(self):
        old_header = (
            "# German translations for infinito-nexus.\n"
            "# Copyright (C) 2026 ORGANIZATION\n"
            "# FIRST AUTHOR <EMAIL@ADDRESS>, 2026.\n"
            "#\n"
            'msgid ""\n'
            'msgstr ""\n'
            '"Report-Msgid-Bugs-To: EMAIL@ADDRESS\\n"\n'
            '"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"\n'
            '"Language-Team: de <LL@li.org>\\n"\n'
            '"Language: de\\n"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "core.po"
            path.write_text(old_header, encoding="utf-8")
            write_catalog(path, read_catalog(path))
            text = path.read_text()  # nocheck: cache-read  written by this test

        for expected in (
            "Kevin Veen-Birkenbach <kevinveenbirkenbach@infinito.nexus>",
            "https://infinito.nexus",
            "Report-Msgid-Bugs-To: contact@infinito.nexus",
            "# This file is distributed under the Infinito.Nexus Community License (Non-Commercial).",
        ):
            self.assertIn(expected, text)
        for placeholder in (
            "ORGANIZATION",
            "FIRST AUTHOR",
            "EMAIL@ADDRESS",
            "FULL NAME",
            "LL@li.org",
        ):
            self.assertNotIn(placeholder, text)

    def test_only_final_translations_are_usable(self):
        catalog = merge(
            build_template([("a", "Done"), ("b", "Fuzzy"), ("c", "Empty")], "core"),
            None,
            "de",
        )
        catalog.get("Done", context="a").string = "Fertig"
        fuzzy = catalog.get("Fuzzy", context="b")
        fuzzy.string = "Unscharf"
        fuzzy.flags.add("fuzzy")

        self.assertEqual(translations(catalog), {("a", "Done"): "Fertig"})


if __name__ == "__main__":
    unittest.main()
