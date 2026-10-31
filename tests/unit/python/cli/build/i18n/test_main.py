from __future__ import annotations

import contextlib
import importlib
import io
import json
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.i18n.catalog import catalog_path, new_catalog, write_catalog
from utils.i18n.languages import LANGUAGES_FILE
from utils.i18n.libretranslate import SERVICE_KEY, SERVICES_FILE, Outcome

cli = importlib.import_module("cli.build.i18n.__main__")

LANGUAGES = """\
en: {name: English, native: English, direction: ltr}
de: {name: German, native: Deutsch, direction: ltr}
fr: {name: French, native: Français, direction: ltr}
zu: {name: Zulu, native: isiZulu, direction: ltr}
"""
SERVES = f"""\
{SERVICE_KEY}:
  serves: [de, fr]
"""


def _catalog(root: Path, code: str, translation: str) -> None:
    catalog = new_catalog("core", code)
    catalog.add("Hello", translation, context="menu:x:title")
    path = catalog_path(root, code, "core")
    path.parent.mkdir(parents=True)
    write_catalog(path, catalog)


def _checkout(case: unittest.TestCase) -> Path:
    """Return a checkout holding the language table and the engine's own coverage.

    Args:
        case: the test whose lifetime the temporary directory follows.
    """
    tmp = TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    (root / LANGUAGES_FILE).parent.mkdir()
    (root / LANGUAGES_FILE).write_text(LANGUAGES, encoding="utf-8")
    (root / SERVICES_FILE).parent.mkdir(parents=True)
    (root / SERVICES_FILE).write_text(SERVES, encoding="utf-8")
    return root


class TestLanguages(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _checkout(self)

    def test_the_matrix_gets_every_language_the_table_names(self) -> None:
        """Not the one engine's coverage: the gateway falls through to a chat
        backend that declares no catalogue, so a language outside
        ``serves`` is translated rather than skipped."""
        with (
            mock.patch.object(cli, "PROJECT_ROOT", self.root),
            mock.patch("sys.stdout", new_callable=io.StringIO) as out,
        ):
            status = cli.languages(["core"])

        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out.getvalue()), ["de", "fr", "zu"])


class TestTranslate(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _checkout(self)
        _catalog(self.root, "de", "Hallo")

    def _run(self, requested: list[str] | None = None) -> tuple[int, mock.Mock, mock.Mock]:
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
            return cli.translate(["core"], requested or []), started, client

    def test_a_code_the_table_does_not_name_is_refused_before_any_deploy(self) -> None:
        status, started, _client = self._run(["xx"])

        self.assertEqual(status, 2)
        started.assert_not_called()

    def test_a_language_whose_catalog_is_not_extracted_yet_starts_nothing(self) -> None:
        """``zu`` is in the table and has no catalog on disk. Reading one would
        raise, and refusing the language would drop it from the set the
        repository promises to translate; it simply has nothing pending."""
        status, started, _client = self._run()

        self.assertEqual(status, 0)
        started.assert_not_called()

    def test_only_languages_with_pending_entries_are_awaited(self) -> None:
        _catalog(self.root, "fr", "")

        status, _started, client = self._run()

        self.assertEqual(status, 0)
        self.assertEqual(client.return_value.wait.call_args.args[0], ["fr"])

    def test_the_engine_languages_are_translated_before_the_chat_ones(self) -> None:
        """A language the engine serves costs a fraction of a chat-served one.

        Measured on this deployment, the engine answers in 0.15s and the chat
        model in about 6s, so running the catalogs in the table's alphabetical
        order spends hours on ``aa`` before it has delivered ``fr``. The
        passes are also what bounds the chat lanes: one model instance
        answered 40 requests of a single catalog with HTTP 503 when every
        core got a lane.
        """
        (self.root / LANGUAGES_FILE).write_text(
            LANGUAGES + "aa: {name: Afar, native: Qafar, direction: ltr}\n",
            encoding="utf-8",
        )
        _catalog(self.root, "aa", "")
        _catalog(self.root, "fr", "")
        seen: list[str] = []

        with mock.patch.object(
            cli, "one_catalog", lambda _client, _domain, code: seen.append(code)
        ):
            status, _started, _client = self._run()

        self.assertEqual(status, 0)
        self.assertEqual(seen, ["fr", "aa"])

    def test_nothing_pending_starts_no_container(self) -> None:
        _catalog(self.root, "fr", "Bonjour")

        status, started, _client = self._run()

        self.assertEqual(status, 0)
        started.assert_not_called()


if __name__ == "__main__":
    unittest.main()
