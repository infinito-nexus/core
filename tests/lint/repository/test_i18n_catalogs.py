import unittest

from utils.cache.files import PROJECT_ROOT
from utils.i18n.catalog import LOCALE_DIR, catalog_path, read_catalog
from utils.i18n.extract import core_messages
from utils.i18n.languages import domain_languages, load_languages
from utils.i18n.placeholders import protected_spans


class TestI18nCatalogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.languages = load_languages(PROJECT_ROOT)
        cls.core = {
            code: read_catalog(catalog_path(PROJECT_ROOT, code, "core"))
            for code in domain_languages(cls.languages, "core")
            if catalog_path(PROJECT_ROOT, code, "core").is_file()
        }

    def test_every_language_has_a_core_catalog(self):
        missing = sorted(set(domain_languages(self.languages, "core")) - set(self.core))
        self.assertEqual(missing, [], "run `make i18n-extract domain=core`")

    def test_no_catalog_for_an_unknown_language(self):
        present = {
            path.name for path in (PROJECT_ROOT / LOCALE_DIR).iterdir() if path.is_dir()
        }
        self.assertEqual(sorted(present - set(self.languages)), [])

    def test_core_catalogs_hold_exactly_the_current_sources(self):
        expected = set(core_messages(PROJECT_ROOT))
        stale = {
            code: sorted(expected ^ {(m.context, m.id) for m in catalog if m.id})[:3]
            for code, catalog in self.core.items()
            if expected != {(m.context, m.id) for m in catalog if m.id}
        }
        self.assertEqual(stale, {}, "run `make i18n-extract domain=core`")

    def test_translations_keep_every_protected_span(self):
        broken = []
        catalogs = [(code, "core", catalog) for code, catalog in self.core.items()]
        for code in domain_languages(self.languages, "docs"):
            path = catalog_path(PROJECT_ROOT, code, "docs")
            if path.is_file():
                catalogs.append((code, "docs", read_catalog(path)))
        for code, domain, catalog in catalogs:
            broken.extend(
                f"{domain}/{code}: {message.context} {message.id!r}"
                for message in catalog
                if isinstance(message.id, str)
                and message.id
                and message.string
                and protected_spans(message.id) != protected_spans(message.string)
            )
        self.assertEqual(broken[:20], [])


if __name__ == "__main__":
    unittest.main()
