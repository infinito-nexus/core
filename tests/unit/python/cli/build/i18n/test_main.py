from __future__ import annotations

import contextlib
import importlib
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.i18n.catalog import catalog_path, new_catalog, write_catalog
from utils.i18n.languages import LANGUAGES_FILE
from utils.i18n.libretranslate import Outcome

cli = importlib.import_module("cli.build.i18n.__main__")

LANGUAGES = """\
en: {name: English, native: English, direction: ltr, libretranslate: true}
de: {name: German, native: Deutsch, direction: ltr, libretranslate: true}
fr: {name: French, native: Français, direction: ltr, libretranslate: true}
"""


def _catalog(root: Path, code: str, translation: str) -> None:
    catalog = new_catalog("core", code)
    catalog.add("Hello", translation, context="menu:x:title")
    path = catalog_path(root, code, "core")
    path.parent.mkdir(parents=True)
    write_catalog(path, catalog)


class TestTranslate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / LANGUAGES_FILE).parent.mkdir()
        (self.root / LANGUAGES_FILE).write_text(LANGUAGES, encoding="utf-8")
        _catalog(self.root, "de", "Hallo")

    def _run(self) -> tuple[int, mock.Mock]:
        started = mock.Mock(return_value=contextlib.nullcontext("http://lt"))
        client = mock.Mock()
        client.return_value.translate.side_effect = lambda texts, code: Outcome(
            ["Bonjour"] * len(texts), 0, 0, ""
        )
        with (
            mock.patch.object(cli, "PROJECT_ROOT", self.root),
            mock.patch.object(cli, "server", started),
            mock.patch.object(cli, "LibreTranslate", client),
        ):
            return cli.translate(["core"], []), started

    def test_only_languages_with_pending_entries_start_the_container(self) -> None:
        _catalog(self.root, "fr", "")

        status, started = self._run()

        self.assertEqual(status, 0)
        self.assertEqual(started.call_args.args[1], ["fr"])

    def test_nothing_pending_starts_no_container(self) -> None:
        _catalog(self.root, "fr", "Bonjour")

        status, started = self._run()

        self.assertEqual(status, 0)
        started.assert_not_called()


if __name__ == "__main__":
    unittest.main()
