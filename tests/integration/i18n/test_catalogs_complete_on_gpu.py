"""On a GPU host every machine-translatable catalog must be complete.

Translating the full language set is only affordable where LibreTranslate can
use a GPU, so this runs nowhere else. It reads the catalogs on disk, which is
what a release ships, not what a translation run reported.

Parsing a catalog dominates the runtime and there are two questions to ask of
each one, so a worker parses its catalog once, answers both, and sends back
two counts instead of the catalog.
"""

from __future__ import annotations

import os
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import ClassVar, NamedTuple

from utils import PROJECT_ROOT
from utils.i18n.catalog import catalog_path, read_catalog
from utils.i18n.languages import DOMAINS, load_languages, translatable
from utils.i18n.libretranslate import accelerated
from utils.i18n.translate import damaged, pending


class Counts(NamedTuple):
    name: str
    pending: int
    damaged: int


def measure(task: tuple[str, str]) -> Counts:
    """Return how many entries of one catalog are untranslated and damaged.

    Args:
        task: the catalog's ``domain/code`` name and its path.
    """
    name, path = task
    catalog = read_catalog(Path(path))
    return Counts(name, len(pending(catalog)), len(damaged(catalog)))


@unittest.skipUnless(accelerated(), "no NVIDIA runtime on this host")
class TestCatalogsCompleteOnGpu(unittest.TestCase):
    root: ClassVar[Path] = Path(PROJECT_ROOT)
    languages: ClassVar[dict] = load_languages(Path(PROJECT_ROOT))
    missing: ClassVar[list[str]] = []
    counts: ClassVar[list[Counts]] = []

    @classmethod
    def setUpClass(cls) -> None:
        tasks: list[tuple[str, str]] = []
        for domain in DOMAINS:
            for code in translatable(cls.languages, domain):
                path = catalog_path(cls.root, code, domain)
                if path.is_file():
                    tasks.append((f"{domain}/{code}", str(path)))
                else:
                    cls.missing.append(f"{domain}/{code}")

        if not tasks:
            return
        workers = min(len(tasks), os.cpu_count() or 1)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            cls.counts = list(pool.map(measure, tasks, chunksize=1))

    def test_every_supported_language_has_a_catalog(self) -> None:
        self.assertEqual(
            self.missing,
            [],
            f"{len(self.missing)} catalogs do not exist yet: {self.missing}. "
            "Create them with `make i18n-extract`, then fill them with "
            "`make i18n-translate`.",
        )

    def test_no_catalog_has_pending_entries(self) -> None:
        incomplete = {c.name: c.pending for c in self.counts if c.pending}

        self.assertEqual(
            incomplete,
            {},
            f"{sum(incomplete.values())} untranslated entries in "
            f"{len(incomplete)} catalogs: {incomplete}. "
            "Fill them with `make i18n-translate` (add domain=core|docs or "
            "languages=de,fr to narrow it down).",
        )

    def test_no_catalog_holds_a_damaged_translation(self) -> None:
        broken = {c.name: c.damaged for c in self.counts if c.damaged}

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
