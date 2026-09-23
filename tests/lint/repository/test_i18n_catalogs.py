import re
import unittest

from utils.cache.files import PROJECT_ROOT
from utils.i18n.catalog import LOCALE_DIR, catalog_path, read_catalog
from utils.i18n.extract import core_messages
from utils.i18n.languages import domain_languages, load_languages
from utils.i18n.placeholders import (
    MARKUP,
    TOKEN,
    mask,
    protected_spans,
    resegment,
    tighten,
)


class TestI18nCatalogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.languages = load_languages(PROJECT_ROOT)
        cls.core = {
            code: read_catalog(catalog_path(PROJECT_ROOT, code, "core"))
            for code in domain_languages(cls.languages, "core")
            if catalog_path(PROJECT_ROOT, code, "core").is_file()
        }
        cls.every = [(code, "core", catalog) for code, catalog in cls.core.items()]
        for code in domain_languages(cls.languages, "docs"):
            path = catalog_path(PROJECT_ROOT, code, "docs")
            if path.is_file():
                cls.every.append((code, "docs", read_catalog(path)))

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

    def test_every_docs_catalog_holds_the_same_sources(self):
        shapes = {
            code: {(m.context, m.id) for m in catalog if m.id}
            for code, domain, catalog in self.every
            if domain == "docs"
        }
        reference = next(iter(shapes.values()), set())
        drifted = sorted(code for code, shape in shapes.items() if shape != reference)
        self.assertEqual(drifted, [], "run `make i18n-extract domain=docs`")

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

    def test_no_source_hands_markup_to_the_translator(self):
        leaking = []
        for code, domain, catalog in self.every:
            leaking.extend(
                f"{domain}/{code}: {message.id!r}"
                for message in catalog
                if isinstance(message.id, str)
                and message.id
                and set(TOKEN.sub("", mask(message.id).text)) & set(MARKUP)
            )
        self.assertEqual(
            leaking[:20],
            [],
            "a construct escapes masking; extend PROTECTED rather than the catalog",
        )

    def test_no_translation_spaces_its_emphasis_open(self):
        loose = []
        for code, domain, catalog in self.every:
            loose.extend(
                f"{domain}/{code}: {message.string!r}"
                for message in catalog
                if isinstance(message.string, str)
                and message.string
                and tighten(message.string) != message.string
            )
        self.assertEqual(
            loose[:20],
            [],
            "markdown renders no emphasis around a space; run prune and translate again",
        )

    def test_no_translation_swallowed_a_sentence_boundary(self):
        merged = []
        for code, domain, catalog in self.every:
            merged.extend(
                f"{domain}/{code}: {message.id!r}"
                for message in catalog
                if isinstance(message.id, str)
                and message.id
                and isinstance(message.string, str)
                and message.string
                and resegment(message.string, mask(message.id).spans, message.id)
                != message.string
            )
        self.assertEqual(
            merged[:20],
            [],
            "a translator read a trailing span as sentence-final and glued the next sentence on",
        )

    def test_no_source_hands_a_quoted_identifier_to_the_translator(self):
        quoted = re.compile(r"['\"][\w.-]+['\"]")
        leaking = []
        for code, domain, catalog in self.every:
            leaking.extend(
                f"{domain}/{code}: {message.id!r}"
                for message in catalog
                if isinstance(message.id, str)
                and message.id
                and quoted.search(TOKEN.sub("", mask(message.id).text))
            )
        self.assertEqual(
            leaking[:20],
            [],
            "a quoted identifier reaches the translator and becomes a different value",
        )


if __name__ == "__main__":
    unittest.main()
