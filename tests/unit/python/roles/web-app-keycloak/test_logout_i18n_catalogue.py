"""The panel's catalogue is data inlined under a CSP hash, so it has no runtime.

A key the template reads but the catalogue lacks renders ``undefined`` into the
page, and a language whose entry is short by one key does it only for the
visitors who speak it. Both are invisible until someone reports them, which is
why the shape is asserted here rather than left to review.

Shape holds whatever the translation pipeline has done, so those cases run
everywhere. Whether an entry carries a translation at all is a different
question: it is only answerable once the engines have run over the catalogs,
which needs a GPU. That case therefore carries the same guard as
``tests/integration/i18n/test_catalogs_complete_on_gpu.py`` and skips where no
engine could have filled anything.
"""

from __future__ import annotations

import re
import unittest

from plugins.lookup.i18n_catalogue import LookupModule
from tests.utils.gpu import FLAG, gpu_tests_enabled
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.i18n.extract import logout_context
from utils.i18n.keyed import keyed_catalogue
from utils.i18n.languages import load_languages

ROLE = PROJECT_ROOT / "roles" / "web-app-keycloak"
CATALOGUE_FILE = ROLE / "files" / "logout_i18n.yml"
CATALOGUE_TERM = "roles/web-app-keycloak/files/logout_i18n.yml"
TEMPLATE = ROLE / "files" / "javascript" / "logout-panel.js"
DASHBOARD_TEMPLATE = (
    PROJECT_ROOT
    / "roles"
    / "web-app-dashboard"
    / "templates"
    / "javascript"
    / "oidc.js.j2"
)
REFERENCE = "en"
MINIMUM_LANGUAGES = 30
TOLERATED_ENGLISH_KEYS = 2
CHOICE_KEYS = ("choice_device", "choice_everywhere")
RESULT_KEYS = ("everywhere_done", "everywhere_partial")


def _keys_read() -> set[str]:
    """Return the catalogue keys the logout panel and the dashboard read."""
    panel = set(re.findall(r"\bs\.([a-z_]+)", read_text(str(TEMPLATE))))
    dashboard = set(
        re.findall(r"\bmessages\.([a-z_]+)", read_text(str(DASHBOARD_TEMPLATE)))
    )
    return panel | dashboard


class TestLogoutCatalogue(unittest.TestCase):
    def setUp(self) -> None:
        self.catalogue = keyed_catalogue(
            PROJECT_ROOT,
            logout_context,
            load_yaml(CATALOGUE_FILE),
            PROJECT_ROOT,
            "core",
        )
        self.template = read_text(str(TEMPLATE))

    def test_the_promised_number_of_languages_is_offered(self) -> None:
        self.assertGreaterEqual(len(self.catalogue), MINIMUM_LANGUAGES)
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

    def test_every_language_takes_its_direction_from_the_language_list(self) -> None:
        languages = load_languages(PROJECT_ROOT)
        for lang, entry in self.catalogue.items():
            with self.subTest(language=lang):
                self.assertEqual(entry["dir"], languages[lang]["direction"])
        self.assertEqual(self.catalogue["ar"]["dir"], "rtl")

    def test_every_key_the_panel_reads_exists_in_every_language(self) -> None:
        used = set(re.findall(r"\bs\.([a-z_]+)", self.template))
        self.assertTrue(used, "the panel no longer reads the catalogue")
        for lang, entry in self.catalogue.items():
            with self.subTest(language=lang):
                self.assertFalse(
                    sorted(used - set(entry)), "keys the panel reads are missing"
                )

    def test_no_catalogue_key_is_dead(self) -> None:
        used = _keys_read() | {"dir"}
        self.assertFalse(sorted(set(self.catalogue[REFERENCE]) - used))

    def test_the_device_success_names_its_scope(self) -> None:
        done = self.catalogue[REFERENCE]["all_done"]
        self.assertIn("this device", done)
        self.assertNotIn("everywhere", done)

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


class TestLogoutChoicesAreTranslated(unittest.TestCase):
    def setUp(self) -> None:
        self.catalogue = LookupModule().run(
            ["logout", CATALOGUE_TERM], variables={"playbook_dir": str(PROJECT_ROOT)}
        )[0]

    def test_every_language_block_translates_the_choices_and_their_outcome(
        self,
    ) -> None:
        reference = self.catalogue[REFERENCE]
        for lang, entry in self.catalogue.items():
            for key in (*CHOICE_KEYS, *RESULT_KEYS):
                with self.subTest(language=lang, key=key):
                    self.assertTrue(str(entry[key]).strip())
                    if lang != REFERENCE:
                        self.assertNotEqual(
                            entry[key],
                            reference[key],
                            "the English fallback is not a translation",
                        )

    def test_the_choices_are_two_different_labels_in_every_language(self) -> None:
        for lang, entry in self.catalogue.items():
            with self.subTest(language=lang):
                self.assertNotEqual(entry["choice_device"], entry["choice_everywhere"])


@unittest.skipUnless(gpu_tests_enabled(), f"{FLAG} is false")
class TestLogoutCatalogueIsTranslated(unittest.TestCase):
    def setUp(self) -> None:
        self.catalogue = keyed_catalogue(
            PROJECT_ROOT,
            logout_context,
            load_yaml(CATALOGUE_FILE),
            PROJECT_ROOT,
            "core",
        )

    def test_translations_are_not_copies_of_english(self) -> None:
        reference = self.catalogue[REFERENCE]
        for lang, entry in self.catalogue.items():
            if lang == REFERENCE:
                continue
            same = [k for k, v in entry.items() if k != "dir" and v == reference[k]]
            with self.subTest(language=lang):
                self.assertLessEqual(
                    len(same),
                    TOLERATED_ENGLISH_KEYS,
                    f"still English: {sorted(same)}",
                )


if __name__ == "__main__":
    unittest.main()
