import tempfile
import unittest
from pathlib import Path

from utils.i18n.catalog import catalog_path, new_catalog, write_catalog
from utils.i18n.keyed import source_keyed_catalogues
from utils.i18n.languages import LANGUAGES_FILE

LANGUAGES = """\
en: {name: English, native: English, direction: ltr, libretranslate: true}
de: {name: German, native: Deutsch, direction: ltr, libretranslate: true}
fr: {name: French, native: Français, direction: ltr, libretranslate: true}
"""


def _catalog(root: Path, code: str, entries: dict[tuple[str, str], str]) -> None:
    catalog = new_catalog("core", code)
    for (context, msgid), msgstr in entries.items():
        catalog.add(msgid, msgstr, context=context)
    path = catalog_path(root, code, "core")
    path.parent.mkdir(parents=True)
    write_catalog(path, catalog)


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
            )
            _catalog(root, "fr", {("role:web-app-x:description", "A wiki"): ""})

            catalogues = source_keyed_catalogues(root, ("role:", "menu:"))

        self.assertEqual(catalogues, {"de": {"A wiki": "Ein Wiki", "Help": "Hilfe"}})


if __name__ == "__main__":
    unittest.main()
