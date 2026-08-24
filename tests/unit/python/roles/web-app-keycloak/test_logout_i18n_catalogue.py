"""The panel's catalogue is data inlined under a CSP hash, so it has no runtime.

A key the template reads but the catalogue lacks renders ``undefined`` into the
page, and a language whose entry is short by one key does it only for the
visitors who speak it. Both are invisible until someone reports them, which is
why the shape is asserted here rather than left to review.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml

ROLE = PROJECT_ROOT / "roles" / "web-app-keycloak"
CATALOGUE_FILE = ROLE / "files" / "logout_i18n.yml"
TEMPLATE = ROLE / "files" / "javascript" / "logout-panel.js"
REFERENCE = "en"
RIGHT_TO_LEFT = {"ar", "fa", "ur"}
EXPECTED_LANGUAGES = 30


class TestLogoutCatalogue(unittest.TestCase):
    def setUp(self) -> None:
        self.catalogue = load_yaml(CATALOGUE_FILE)
        self.template = read_text(str(TEMPLATE))

    def test_the_promised_number_of_languages_is_offered(self) -> None:
        self.assertEqual(len(self.catalogue), EXPECTED_LANGUAGES)
        self.assertIn(
            REFERENCE, self.catalogue, "English is the fallback and must exist"
        )

    def test_every_language_carries_every_key(self) -> None:
        expected = set(self.catalogue[REFERENCE])
        for lang, entry in self.catalogue.items():
            with self.subTest(language=lang):
                self.assertEqual(
                    set(entry),
                    expected,
                    f"diverges by {sorted(set(entry) ^ expected)}",
                )

    def test_no_string_is_empty(self) -> None:
        for lang, entry in self.catalogue.items():
            for key, value in entry.items():
                with self.subTest(language=lang, key=key):
                    self.assertTrue(
                        str(value).strip(), "empty strings render as nothing"
                    )

    def test_right_to_left_languages_are_marked_and_others_are_not(self) -> None:
        for lang, entry in self.catalogue.items():
            with self.subTest(language=lang):
                self.assertEqual(
                    entry["dir"], "rtl" if lang in RIGHT_TO_LEFT else "ltr"
                )

    def test_every_key_the_panel_reads_exists_in_every_language(self) -> None:
        used = set(re.findall(r"\bs\.([a-z_]+)", self.template))
        self.assertTrue(used, "the panel no longer reads the catalogue")
        for lang, entry in self.catalogue.items():
            with self.subTest(language=lang):
                self.assertFalse(
                    sorted(used - set(entry)), "keys the panel reads are missing"
                )

    def test_no_catalogue_key_is_dead(self) -> None:
        used = set(re.findall(r"\bs\.([a-z_]+)", self.template)) | {"dir"}
        self.assertFalse(sorted(set(self.catalogue[REFERENCE]) - used))

    def test_placeholders_survive_translation(self) -> None:
        reference = self.catalogue[REFERENCE]
        for lang, entry in self.catalogue.items():
            for key, value in entry.items():
                expected = set(re.findall(r"\{(\w+)\}", str(reference[key])))
                with self.subTest(language=lang, key=key):
                    self.assertEqual(
                        set(re.findall(r"\{(\w+)\}", str(value))),
                        expected,
                        "a dropped or renamed placeholder leaves a literal brace on screen",
                    )

    def test_translations_are_not_copies_of_english(self) -> None:
        reference = self.catalogue[REFERENCE]
        for lang, entry in self.catalogue.items():
            if lang == REFERENCE:
                continue
            same = [k for k, v in entry.items() if k != "dir" and v == reference[k]]
            with self.subTest(language=lang):
                self.assertLessEqual(len(same), 2, f"still English: {sorted(same)}")


if __name__ == "__main__":
    unittest.main()
