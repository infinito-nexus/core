"""The ISO 639-1 to FLORES-200 boundary NLLB-200 is reached across."""

from __future__ import annotations

import re
import unicodedata
import unittest

from utils.cache.yaml import load_yaml

from . import FLORES, PROJECT_ROOT

LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

SCRIPTS = {
    "ARABIC": "Arab",
    "ARMENIAN": "Armn",
    "BENGALI": "Beng",
    "CYRILLIC": "Cyrl",
    "DEVANAGARI": "Deva",
    "ETHIOPIC": "Ethi",
    "GEORGIAN": "Geor",
    "GREEK": "Grek",
    "GUJARATI": "Gujr",
    "GURMUKHI": "Guru",
    "HANGUL": "Hang",
    "HEBREW": "Hebr",
    "KANNADA": "Knda",
    "KHMER": "Khmr",
    "LAO": "Laoo",
    "LATIN": "Latn",
    "MALAYALAM": "Mlym",
    "MYANMAR": "Mymr",
    "ORIYA": "Orya",
    "SINHALA": "Sinh",
    "TAMIL": "Taml",
    "TELUGU": "Telu",
    "THAI": "Thai",
    "TIBETAN": "Tibt",
}

HAN_SCRIPTED = frozenset({"ja", "zh"})
NORWEGIAN = frozenset({"nb", "no"})


def endonym_script(native: str) -> str | None:
    """Return the ISO 15924 script the majority of this endonym is written in.

    The script of a letter rather than its codepoint range, the same evidence
    ``utils.i18n.languages`` reads to tell a Latin table entry from a
    non-Latin one.

    Args:
        native: the endonym as ``meta/languages.yml`` records it.
    """
    tally: dict[str, int] = {}
    for char in native:
        if not LETTER.match(char):
            continue
        name = unicodedata.name(char, "")
        for prefix, script in SCRIPTS.items():
            if name.startswith(prefix):
                tally[script] = tally.get(script, 0) + 1
                break
    if not tally:
        return None
    return max(tally.items(), key=lambda entry: entry[1])[0]


def languages() -> dict[str, dict]:
    return load_yaml(PROJECT_ROOT / "meta" / "languages.yml")


class CoverageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.languages = languages()

    def test_every_mapped_code_is_one_the_model_carries(self) -> None:
        unknown = sorted(set(FLORES.ISO_TO_FLORES.values()) - FLORES.SERVED)

        self.assertEqual(unknown, [])

    def test_no_two_languages_claim_the_same_model_language(self) -> None:
        """A duplicate means one of the two subtags is the wrong variety.

        NLLB ships one individual variety per macrolanguage, so a mistake
        there reads as a working translation into a neighbouring language,
        which is exactly the failure the chat backend produced when it
        answered Belarusian in Polish. Norwegian is the one allowed
        collision: the table carries the macrolanguage and Bokmål as
        separate catalogs and NLLB has one code for both.
        """
        mapped = [
            flores
            for iso, flores in FLORES.ISO_TO_FLORES.items()
            if iso not in NORWEGIAN
        ]

        self.assertEqual(len(mapped), len(set(mapped)))
        self.assertEqual({FLORES.ISO_TO_FLORES[iso] for iso in NORWEGIAN}, {"nob_Latn"})

    def test_the_table_accounts_for_every_language_of_the_repository(self) -> None:
        """Mapped plus unserved is the table, exactly: no gap, no overlap."""
        self.assertEqual(
            set(FLORES.ISO_TO_FLORES) | FLORES.UNSERVED, set(self.languages)
        )
        self.assertEqual(set(FLORES.ISO_TO_FLORES) & FLORES.UNSERVED, set())

    def test_the_declared_ceiling_is_a_real_one(self) -> None:
        """Nothing is listed as unserved that the model in fact carries."""
        self.assertNotIn("be", FLORES.UNSERVED)
        self.assertNotIn("am", FLORES.UNSERVED)
        self.assertIn("ab", FLORES.UNSERVED)
        self.assertIn("av", FLORES.UNSERVED)


class ScriptTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.languages = languages()

    def test_every_script_suffix_agrees_with_the_endonym(self) -> None:
        """The endonym is the evidence for the script half of the code.

        Japanese and Chinese are excluded because their endonyms are written
        in Han ideographs, which cannot tell ``Jpan`` from ``Hans`` from
        ``Hant``; the subtag decides those and there is nothing to check
        them against here.
        """
        for iso, flores in sorted(FLORES.ISO_TO_FLORES.items()):
            if iso in HAN_SCRIPTED:
                continue
            native = str(self.languages[iso].get("native", ""))
            derived = endonym_script(native)
            if derived is None:
                continue
            with self.subTest(iso=iso, native=native):
                self.assertEqual(flores.split("_")[1], derived)


class CodeTestCase(unittest.TestCase):
    def test_a_served_language_resolves(self) -> None:
        self.assertEqual(FLORES.code("be"), "bel_Cyrl")
        self.assertEqual(FLORES.code("am"), "amh_Ethi")

    def test_a_macrolanguage_resolves_to_the_variety_the_model_ships(self) -> None:
        self.assertEqual(FLORES.code("ar"), "arb_Arab")
        self.assertEqual(FLORES.code("fa"), "pes_Arab")
        self.assertEqual(FLORES.code("ms"), "zsm_Latn")
        self.assertEqual(FLORES.code("mn"), "khk_Cyrl")

    def test_an_unserved_language_fails_loudly_and_names_itself(self) -> None:
        with self.assertRaises(ValueError) as caught:
            FLORES.code("ab")

        self.assertIn("ab", str(caught.exception))


class PairsTestCase(unittest.TestCase):
    def test_the_catalogue_is_both_directions_without_the_identity(self) -> None:
        pairs = FLORES.pairs()

        self.assertIn(("en", "be"), pairs)
        self.assertIn(("be", "en"), pairs)
        self.assertNotIn(("en", "en"), pairs)

    def test_an_unserved_language_is_in_no_pair(self) -> None:
        pairs = FLORES.pairs()

        self.assertNotIn(("en", "ab"), pairs)
        self.assertNotIn(("ab", "en"), pairs)


if __name__ == "__main__":
    unittest.main()
