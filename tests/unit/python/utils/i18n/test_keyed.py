import tempfile
import unittest
from pathlib import Path

from utils.i18n.catalog import catalog_path, new_catalog, write_catalog
from utils.i18n.keyed import keyed_catalogue, source_keyed_catalogues
from utils.i18n.languages import LANGUAGES_FILE

LANGUAGES = """\
en: {name: English, native: English, direction: ltr, libretranslate: true}
de: {name: German, native: Deutsch, direction: ltr, libretranslate: true}
fr: {name: French, native: Français, direction: ltr, libretranslate: true}
"""


def _catalog(
    root: Path, code: str, entries: dict[tuple[str, str], str], domain: str
) -> None:
    catalog = new_catalog(domain, code)
    for (context, msgid), msgstr in entries.items():
        catalog.add(msgid, msgstr, context=context)
    path = catalog_path(root, code, domain)
    path.parent.mkdir(parents=True)
    write_catalog(path, catalog)


class TestKeyedCatalogue(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "core"
        self.role = Path(tmp.name) / "role"
        (self.root / LANGUAGES_FILE).parent.mkdir(parents=True)
        (self.root / LANGUAGES_FILE).write_text(LANGUAGES, encoding="utf-8")
        _catalog(self.root, "de", {("team:title", "The team"): "Kern"}, "core")
        _catalog(self.role, "de", {("team:title", "The team"): "Das Team"}, "team")

    def _read(self, catalogs: Path, domain: str) -> dict:
        return keyed_catalogue(
            self.root,
            lambda key: f"team:{key}",
            {"title": "The team"},
            catalogs,
            domain,
        )

    def test_a_role_catalog_is_read_from_the_role(self) -> None:
        self.assertEqual(self._read(self.role, "team")["de"]["title"], "Das Team")

    def test_without_the_role_core_catalogs_answer(self) -> None:
        self.assertEqual(self._read(self.root, "core")["de"]["title"], "Kern")


class TestSourceKeyedCatalogues(unittest.TestCase):
    def test_only_prefixed_translations_are_keyed_by_their_english_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / LANGUAGES_FILE).parent.mkdir()
            (root / LANGUAGES_FILE).write_text(LANGUAGES, encoding="utf-8")
            _catalog(
                root,
                "de",
                {
                    ("role:web-app-x:description", "A wiki"): "Ein Wiki",
                    ("menu:help:title", "Help"): "Hilfe",
                    ("logout:checking", "Checking"): "Prüfe",
                },
                "core",
            )
            _catalog(root, "fr", {("role:web-app-x:description", "A wiki"): ""}, "core")

            catalogues = source_keyed_catalogues(root, ("role:", "menu:"))

        self.assertEqual(catalogues, {"de": {"A wiki": "Ein Wiki", "Help": "Hilfe"}})


if __name__ == "__main__":
    unittest.main()
