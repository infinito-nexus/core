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


class TestMerge(unittest.TestCase):
    def test_changed_source_keeps_translation_as_fuzzy(self):
        catalog = merge(build_template([("a", "Hello world")], "core"), None, "de")
        catalog.get("Hello world", context="a").string = "Hallo Welt"

        merged = merge(build_template([("a", "Hello world!")], "core"), catalog, "de")

        message = merged.get("Hello world!", context="a")
        self.assertEqual(message.string, "Hallo Welt")
        self.assertTrue(message.fuzzy)

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
