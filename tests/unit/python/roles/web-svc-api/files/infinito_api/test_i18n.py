from __future__ import annotations

import importlib
import io
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-api" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

repository = importlib.import_module("infinito_api.repository")
i18n = importlib.import_module("infinito_api.i18n")

LANGUAGES = """\
en:
  name: English
  native: English
  direction: ltr
de:
  name: German
  native: Deutsch
  direction: ltr
ar:
  name: Arabic
  native: العربية
  direction: rtl
"""


def _catalog() -> bytes:
    catalog = Catalog(locale="de")
    catalog.add("A wiki", "Ein Wiki", context="role:web-app-x:description")
    catalog.add("Old", "Alt", context="role:web-app-y:description", flags=["fuzzy"])
    catalog.add("Empty", "", context="role:web-app-z:description")
    buffer = io.BytesIO()
    write_po(buffer, catalog)
    return buffer.getvalue()


class TestAccepted(unittest.TestCase):
    def test_primary_subtags_are_ranked_by_quality_then_order(self) -> None:
        self.assertEqual(
            i18n.accepted("fr-CH, fr;q=0.9, de-DE;q=0.95, *;q=0.5, xx;q=0"),
            ["fr", "de", "fr"],
        )
        self.assertEqual(i18n.accepted("en;q=broken, de"), ["de"])
        self.assertEqual(i18n.accepted(None), [])


class TestTranslations(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        snapshot = root / "snapshot"
        (snapshot / "meta").mkdir(parents=True)
        (snapshot / "meta" / "languages.yml").write_text(LANGUAGES, encoding="utf-8")
        catalog = snapshot / "locale" / "de" / "LC_MESSAGES" / "core.po"
        catalog.parent.mkdir(parents=True)
        catalog.write_bytes(_catalog())
        (root / "data").mkdir()
        self.repo = repository.Repository(
            root / "data" / "repo.git",
            "https://github.com/infinito-nexus/core.git",
            "off",
            snapshot,
        )
        self.repo.initialize()
        self.commit = self.repo.resolve("deployed")
        self.translations = i18n.Translations(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_the_parameter_wins_and_the_header_falls_back_to_english(self) -> None:
        self.assertEqual(self.translations.negotiate(self.commit, "ar", "de"), "ar")
        self.assertEqual(
            self.translations.negotiate(self.commit, None, "fr, de;q=0.8"), "de"
        )
        self.assertEqual(self.translations.negotiate(self.commit, None, "fr"), "en")
        with self.assertRaises(repository.NotFoundError):
            self.translations.negotiate(self.commit, "xx", None)

    def test_only_final_translations_are_served(self) -> None:
        german = self.translations.translator(self.commit, "de")

        self.assertEqual(
            german.text("role:web-app-x:description", "A wiki"), "Ein Wiki"
        )
        self.assertEqual(german.text("role:web-app-y:description", "Old"), "Old")
        self.assertEqual(
            german.text("role:web-app-x:description", "Changed"), "Changed"
        )
        self.assertAlmostEqual(
            self.translations.completeness(self.commit, "de"), 0.3333
        )
        self.assertEqual(self.translations.completeness(self.commit, "en"), 1.0)
        self.assertEqual(self.translations.completeness(self.commit, "ar"), 0.0)

    def test_a_ref_without_catalogs_is_translated_with_the_deployed_ones(self) -> None:
        empty_tree = (
            self.repo.git("hash-object", "-t", "tree", "--stdin", stdin=b"")
            .decode()
            .strip()
        )
        identity = dict.fromkeys(
            (
                "GIT_AUTHOR_NAME",
                "GIT_AUTHOR_EMAIL",
                "GIT_COMMITTER_NAME",
                "GIT_COMMITTER_EMAIL",
            ),
            "t",
        )
        bare = (
            self.repo.git(
                "commit-tree",
                empty_tree,
                "-m",
                "old release",
                env={**os.environ, **identity},
            )
            .decode()
            .strip()
        )

        self.assertEqual(self.translations.catalog_commit(bare), self.commit)
        self.assertEqual(sorted(self.translations.languages(bare)), ["ar", "de", "en"])
        self.assertEqual(
            self.translations.translator(bare, "de").text(
                "role:web-app-x:description", "A wiki"
            ),
            "Ein Wiki",
        )


if __name__ == "__main__":
    unittest.main()
