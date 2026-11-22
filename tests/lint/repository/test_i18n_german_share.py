import importlib
import io
import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po

from utils.cache.files import PROJECT_ROOT, read_text
from utils.software import SOFTWARE_REPOSITORY

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-api" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

repository = importlib.import_module("infinito_api.repository")
i18n = importlib.import_module("infinito_api.i18n")

LANGUAGE = "de"
SPEC = PROJECT_ROOT / "roles" / "web-svc-api" / "files" / "playwright" / "test-i18n.js"
FLOOR = re.compile(r"byCode\.de\.translated\)\.toBeGreaterThan\((\d+(?:\.\d+)?)\)")
FAILED_RUN_TRANSLATED = 431
FAILED_RUN_ENTRIES = 636


def served_share(catalog: bytes) -> float:
    """Return the translated share the API serves for a deployed German catalog.

    Args:
        catalog: content of the German ``core`` catalog.
    """
    with TemporaryDirectory() as scratch:
        root = Path(scratch)
        snapshot = root / "snapshot"
        target = snapshot / i18n.catalog_file(LANGUAGE)
        target.parent.mkdir(parents=True)
        target.write_bytes(catalog)
        (root / "data").mkdir()
        repo = repository.Repository(
            root / "data" / "repo.git", SOFTWARE_REPOSITORY, "off", snapshot
        )
        repo.initialize()
        return i18n.Translations(repo).completeness(
            repo.resolve(repository.DEPLOYED), LANGUAGE
        )


def failed_run_catalog() -> bytes:
    catalog = Catalog(locale=LANGUAGE)
    for index in range(FAILED_RUN_ENTRIES):
        catalog.add(
            f"Source {index}",
            f"Quelle {index}" if index < FAILED_RUN_TRANSLATED else "",
            context=f"role:web-app-{index}:description",
        )
    buffer = io.BytesIO()
    write_po(buffer, catalog)
    return buffer.getvalue()


class TestI18nGermanShare(unittest.TestCase):
    def setUp(self) -> None:
        match = FLOOR.search(read_text(str(SPEC)))
        self.assertIsNotNone(match, f"{SPEC} no longer states the German floor")
        self.floor = float(match.group(1))

    def test_the_shipped_catalog_clears_the_floor_of_the_languages_spec(self) -> None:
        shipped = read_text(str(PROJECT_ROOT / i18n.catalog_file(LANGUAGE)))
        self.assertGreater(
            served_share(shipped.encode("utf-8")),
            self.floor,
            "run `make i18n-translate domain=core languages=de`",
        )

    def test_the_catalog_of_the_failed_run_stays_below_the_floor(self) -> None:
        share = served_share(failed_run_catalog())
        self.assertAlmostEqual(
            share, FAILED_RUN_TRANSLATED / FAILED_RUN_ENTRIES, places=4
        )
        self.assertLessEqual(share, self.floor)


if __name__ == "__main__":
    unittest.main()
