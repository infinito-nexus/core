"""On a GPU host every machine-translatable catalog must be complete.

Translating the full language set is only affordable where LibreTranslate can
use a GPU, so this runs nowhere else. It reads the catalogs on disk, which is
what a release ships, not what a translation run reported.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import ClassVar

from utils import PROJECT_ROOT
from utils.i18n.catalog import catalog_path, read_catalog
from utils.i18n.languages import DOMAINS, load_languages, translatable
from utils.i18n.libretranslate import accelerated
from utils.i18n.translate import damaged, pending


@unittest.skipUnless(accelerated(), "no NVIDIA runtime on this host")
class TestCatalogsCompleteOnGpu(unittest.TestCase):
    root: ClassVar[Path] = Path(PROJECT_ROOT)
    languages: ClassVar[dict] = load_languages(Path(PROJECT_ROOT))

    def _catalogs(self):
        for domain in DOMAINS:
            for code in translatable(self.languages, domain):
                path = catalog_path(self.root, code, domain)
                if path.is_file():
                    yield domain, code, read_catalog(path)

    def test_every_supported_language_has_a_catalog(self) -> None:
        missing = [
            f"{domain}/{code}"
            for domain in DOMAINS
            for code in translatable(self.languages, domain)
            if not catalog_path(self.root, code, domain).is_file()
        ]

        self.assertEqual(
            missing,
            [],
            f"{len(missing)} catalogs do not exist yet: {missing}. "
            "Create them with `make i18n-extract`, then fill them with "
            "`make i18n-translate`.",
        )

    def test_no_catalog_has_pending_entries(self) -> None:
        incomplete = {
            f"{domain}/{code}": len(pending(catalog))
            for domain, code, catalog in self._catalogs()
            if pending(catalog)
        }

        self.assertEqual(
            incomplete,
            {},
            f"{sum(incomplete.values())} untranslated entries in "
            f"{len(incomplete)} catalogs: {incomplete}. "
            "Fill them with `make i18n-translate` (add domain=core|docs or "
            "languages=de,fr to narrow it down).",
        )

    def test_no_catalog_holds_a_damaged_translation(self) -> None:
        broken = {
            f"{domain}/{code}": len(damaged(catalog))
            for domain, code, catalog in self._catalogs()
            if damaged(catalog)
        }

        self.assertEqual(
            broken,
            {},
            f"{sum(broken.values())} translations altered a protected span in "
            f"{len(broken)} catalogs: {broken}. "
            "Empty them with `make i18n-prune`, then redo them with "
            "`make i18n-translate`.",
        )


if __name__ == "__main__":
    unittest.main()
