"""Every shipped catalog parses, matches its sources and kept its protections.

Each question below has to look at every message of every catalog, and there
are around fifty catalogs per domain. One worker therefore reads its catalog
once, answers all of them, and sends back a handful of strings instead of the
catalog: the findings are capped, and the source shape travels as a digest.
"""

import hashlib
import os
import re
import unittest
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from babel.messages.catalog import Message, TranslationError
from babel.messages.checkers import python_format

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

SAMPLE = 20
QUOTED = re.compile(r"['\"][\w.-]+['\"]")

_EXPECTED: set = set()


@dataclass
class Findings:
    """What one catalog answered, in the words its test reports."""

    code: str
    domain: str
    uncompilable: int = 0
    shape: str = ""
    stale: list = field(default_factory=list)
    markup: list = field(default_factory=list)
    quoted: list = field(default_factory=list)
    spans: list = field(default_factory=list)
    merged: list = field(default_factory=list)
    loose: list = field(default_factory=list)


def _load_expected() -> None:
    global _EXPECTED  # noqa: PLW0603 — one read per worker, not per catalog
    _EXPECTED = set(core_messages(PROJECT_ROOT))


def _rejects(catalog, message, string) -> bool:
    try:
        python_format(catalog, Message(message.id, string, flags=message.flags))
    except TranslationError:
        return True
    return False


def inspect(task: tuple[str, str, str]) -> Findings:
    """Answer every catalog question for one catalog.

    Args:
        task: the language code, the domain and the catalog's path.
    """
    code, domain, path = task
    catalog = read_catalog(Path(path))
    found = Findings(code, domain)
    where = f"{domain}/{code}"
    shape = set()

    for message in catalog:
        source, translation = message.id, message.string
        if not isinstance(source, str) or not source:
            continue
        shape.add((message.context, source))

        if isinstance(translation, str) and translation:
            if (
                "no-python-format" not in message.flags
                and not _rejects(catalog, message, source)
                and _rejects(catalog, message, translation)
            ):
                found.uncompilable += 1
            if protected_spans(source) != protected_spans(translation):
                found.spans.append(f"{where}: {message.context} {source!r}")
            if resegment(translation, mask(source).spans, source) != translation:
                found.merged.append(f"{where}: {source!r}")
            if tighten(translation) != translation:
                found.loose.append(f"{where}: {translation!r}")

        bare = TOKEN.sub("", mask(source).text)
        if set(bare) & set(MARKUP):
            found.markup.append(f"{where}: {source!r}")
        if QUOTED.search(bare):
            found.quoted.append(f"{where}: {source!r}")

    found.shape = hashlib.sha256(
        repr(sorted(shape, key=repr)).encode("utf-8")
    ).hexdigest()
    if domain == "core" and shape != _EXPECTED:
        found.stale = sorted(_EXPECTED ^ shape, key=repr)[:3]

    for capped in (found.markup, found.quoted, found.spans, found.merged, found.loose):
        del capped[SAMPLE:]
    return found


class TestI18nCatalogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.languages = load_languages(PROJECT_ROOT)
        cls.present = {
            domain: [
                code
                for code in domain_languages(cls.languages, domain)
                if catalog_path(PROJECT_ROOT, code, domain).is_file()
            ]
            for domain in ("core", "docs")
        }
        tasks = [
            (code, domain, str(catalog_path(PROJECT_ROOT, code, domain)))
            for domain in ("core", "docs")
            for code in cls.present[domain]
        ]
        if not tasks:
            cls.findings = []
            return
        workers = min(len(tasks), os.cpu_count() or 1)
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_load_expected
        ) as pool:
            cls.findings = list(pool.map(inspect, tasks, chunksize=1))

    def _all(self, attribute: str) -> list:
        return [entry for found in self.findings for entry in getattr(found, attribute)]

    def test_every_language_has_a_core_catalog(self):
        missing = sorted(
            set(domain_languages(self.languages, "core")) - set(self.present["core"])
        )
        self.assertEqual(missing, [], "run `make i18n-extract domain=core`")

    def test_every_catalog_compiles(self):
        broken = {
            f"{f.domain}/{f.code}": f.uncompilable
            for f in self.findings
            if f.uncompilable
        }
        self.assertEqual(
            broken,
            {},
            f"{sum(broken.values())} translations carry placeholders msgfmt "
            f"rejects, so these catalogs do not compile: {broken}. Empty them "
            "with `make i18n-prune`, then redo them with `make i18n-translate`.",
        )

    def test_no_catalog_for_an_unknown_language(self):
        present = {
            path.name for path in (PROJECT_ROOT / LOCALE_DIR).iterdir() if path.is_dir()
        }
        self.assertEqual(sorted(present - set(self.languages)), [])

    def test_core_catalogs_hold_exactly_the_current_sources(self):
        stale = {f.code: f.stale for f in self.findings if f.stale}
        self.assertEqual(stale, {}, "run `make i18n-extract domain=core`")

    def test_every_docs_catalog_holds_the_same_sources(self):
        shapes = {f.code: f.shape for f in self.findings if f.domain == "docs"}
        reference = next(iter(shapes.values()), "")
        drifted = sorted(code for code, shape in shapes.items() if shape != reference)
        self.assertEqual(drifted, [], "run `make i18n-extract domain=docs`")

    def test_translations_keep_every_protected_span(self):
        self.assertEqual(self._all("spans")[:SAMPLE], [])

    def test_no_source_hands_markup_to_the_translator(self):
        self.assertEqual(
            self._all("markup")[:SAMPLE],
            [],
            "a construct escapes masking; extend PROTECTED rather than the catalog",
        )

    def test_no_translation_spaces_its_emphasis_open(self):
        self.assertEqual(
            self._all("loose")[:SAMPLE],
            [],
            "markdown renders no emphasis around a space; run prune and translate again",
        )

    def test_no_translation_swallowed_a_sentence_boundary(self):
        self.assertEqual(
            self._all("merged")[:SAMPLE],
            [],
            "a translator read a trailing span as sentence-final and glued the next sentence on",
        )

    def test_no_source_hands_a_quoted_identifier_to_the_translator(self):
        self.assertEqual(
            self._all("quoted")[:SAMPLE],
            [],
            "a quoted identifier reaches the translator and becomes a different value",
        )


if __name__ == "__main__":
    unittest.main()
