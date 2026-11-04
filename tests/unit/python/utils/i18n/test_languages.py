import unittest

from utils import PROJECT_ROOT
from utils.i18n.languages import (
    DOMAINS,
    SOURCE_LANGUAGE,
    domain_languages,
    language_scripts,
    load_languages,
    non_latin_languages,
    script,
)
from utils.i18n.libretranslate import PIVOT_LANGUAGE, baked_languages, served_languages

FIELDS = {"name", "native", "direction"}
DIRECTIONS = {"ltr", "rtl"}


class TestDomainLanguages(unittest.TestCase):
    def test_a_domain_the_file_does_not_name_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            domain_languages({"de": {}}, "handbook")

    def test_the_source_language_carries_no_catalog_of_its_own(self) -> None:
        self.assertNotIn(
            SOURCE_LANGUAGE, domain_languages({"de": {}, SOURCE_LANGUAGE: {}}, "core")
        )


class TestTheLanguageTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.languages = load_languages(PROJECT_ROOT)

    def test_every_entry_carries_the_three_identity_fields(self) -> None:
        self.assertEqual(
            sorted(
                code for code, entry in self.languages.items() if set(entry) != FIELDS
            ),
            [],
        )

    def test_no_entry_names_an_engine_or_a_scorer(self) -> None:
        """The gateway learns the engine per language and the oracle asks one
        judge for all of them, so a route written here would be a second
        opinion that goes stale as soon as either learns something."""
        self.assertEqual(
            sorted(
                code
                for code, entry in self.languages.items()
                if {"engine", "oracle", "libretranslate"} & set(entry)
            ),
            [],
        )

    def test_every_direction_is_one_of_the_two_writing_directions(self) -> None:
        self.assertEqual(
            sorted(
                code
                for code, entry in self.languages.items()
                if entry["direction"] not in DIRECTIONS
            ),
            [],
        )

    def test_every_language_but_the_source_carries_a_catalog(self) -> None:
        expected = sorted(code for code in self.languages if code != SOURCE_LANGUAGE)
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                self.assertEqual(domain_languages(self.languages, domain), expected)


class TestTheScriptOfEachLanguage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scripts = language_scripts(PROJECT_ROOT)

    def test_a_language_takes_the_script_of_its_endonym(self) -> None:
        self.assertEqual(
            {code: self.scripts[code] for code in ("ur", "hi", "ar", "ja", "ko", "de")},
            {
                "ur": "ARABIC",
                "hi": "DEVANAGARI",
                "ar": "ARABIC",
                "ja": "CJK",
                "ko": "HANGUL",
                "de": "LATIN",
            },
        )

    def test_every_non_latin_language_names_a_script_other_than_latin(self) -> None:
        self.assertEqual(
            sorted(
                code
                for code in non_latin_languages(PROJECT_ROOT)
                if self.scripts.get(code) in (None, "LATIN")
            ),
            [],
        )

    def test_a_character_without_a_name_has_no_script(self) -> None:
        self.assertEqual(script(chr(0xE000)), "")

    def test_a_letter_names_its_script(self) -> None:
        self.assertEqual(
            [script(char) for char in "aاहя日ー"],
            ["LATIN", "ARABIC", "DEVANAGARI", "CYRILLIC", "CJK", "KATAKANA"],
        )


class TestTheEnginesOwnCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.languages = load_languages(PROJECT_ROOT)
        cls.served = served_languages(PROJECT_ROOT)

    def test_every_served_code_is_a_language_the_repository_names(self) -> None:
        self.assertEqual(sorted(set(self.served) - set(self.languages)), [])

    def test_the_lane_bakes_the_pivot_beside_every_served_model(self) -> None:
        self.assertEqual(
            baked_languages(PROJECT_ROOT),
            sorted({PIVOT_LANGUAGE, *self.served}),
        )


if __name__ == "__main__":
    unittest.main()
