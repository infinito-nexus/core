from __future__ import annotations

import importlib
import sys
import unittest

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-access-request" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

i18n = importlib.import_module("access_request.i18n")

CATALOGUE = {
    "en": {"dir": "ltr", "greeting": "Hello {name}", "only_en": "English"},
    "de": {"dir": "ltr", "greeting": "Hallo {name}"},
    "ar": {"dir": "rtl", "greeting": "مرحبا {name}"},
}
RBAC = {
    "en": {"web-app-blog/editor": "Writes posts"},
    "de": {"web-app-blog/editor": "Schreibt Beiträge"},
}


class TestLanguages(unittest.TestCase):
    def test_the_codes_follow_the_quality_and_add_the_base_language(self):
        self.assertEqual(
            ["fr", "de-at", "de"], i18n.languages("de-AT;q=0.8, fr, *;q=0.1")
        )

    def test_an_unparsable_quality_ranks_last(self):
        self.assertEqual(["en", "de"], i18n.languages("de;q=x, en"))

    def test_an_empty_header_names_no_language(self):
        self.assertEqual([], i18n.languages(""))


class TestMessages(unittest.TestCase):
    def test_the_best_known_language_is_picked(self):
        messages = i18n.Messages(CATALOGUE, RBAC, "fr, de-CH;q=0.9")

        self.assertEqual("de", messages.code)
        self.assertEqual("Hallo Biber", messages("greeting", name="Biber"))

    def test_a_missing_key_falls_back_to_english(self):
        messages = i18n.Messages(CATALOGUE, RBAC, "de")

        self.assertEqual("English", messages("only_en"))

    def test_an_unknown_language_falls_back_to_english(self):
        messages = i18n.Messages(CATALOGUE, RBAC, "fr")

        self.assertEqual(i18n.SOURCE_LANGUAGE, messages.code)

    def test_the_direction_follows_the_language(self):
        self.assertEqual("rtl", i18n.Messages(CATALOGUE, RBAC, "ar").direction)

    def test_a_role_description_is_translated_or_kept(self):
        messages = i18n.Messages(CATALOGUE, RBAC, "de")

        self.assertEqual(
            "Schreibt Beiträge", messages.role("web-app-blog", "editor", "Writes")
        )
        self.assertEqual("Reads", messages.role("web-app-blog", "reader", "Reads"))


if __name__ == "__main__":
    unittest.main()
