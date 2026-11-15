from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.i18n.catalog import (
    catalog_path,
    judge_failure,
    machine_translation,
    new_catalog,
    read_catalog,
    write_catalog,
)
from utils.i18n.languages import LANGUAGES_FILE
from utils.i18n.libretranslate import SERVICE_KEY, SERVICES_FILE, Outcome
from utils.i18n.translate import record_judged

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

    def _run(
        self, requested: list[str] | None = None
    ) -> tuple[int, mock.Mock, mock.Mock]:
        started = mock.Mock(return_value=contextlib.nullcontext("http://lt"))
        client = mock.Mock()
        client.return_value.translate.side_effect = lambda texts, code, exclude=(): (
            Outcome(["Bonjour"] * len(texts), 0, 0, "")
        )
        with (
            mock.patch.object(cli, "PROJECT_ROOT", self.root),
            mock.patch.object(cli, "server", started),
            mock.patch.object(cli, "LibreTranslate", client),
        ):
            return (
                cli.translate(["core"], requested or [], False, None),
                started,
                client,
            )

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
            cli, "one_catalog", lambda _client, _root, _domain, code: seen.append(code)
        ):
            status, _started, _client = self._run()

        self.assertEqual(status, 0)
        self.assertEqual(seen, ["fr", "aa"])

    def test_nothing_pending_starts_no_container(self) -> None:
        _catalog(self.root, "fr", "Bonjour")

        status, started, _client = self._run()

        self.assertEqual(status, 0)
        started.assert_not_called()


class TestAJudgedFailureIsRetranslatedWithoutItsEngine(unittest.TestCase):
    """The judge pass of ``make test-oracle`` failed ``Hello``'s translation by
    ``engine-a``; the next ``i18n-translate`` asks for it with that engine
    excluded, and for every untouched pending entry with nothing excluded."""

    def setUp(self) -> None:
        self.root = _checkout(self)
        catalog = new_catalog("core", "de")
        catalog.add("Hello", "Hallo Welt", context="menu:x:title")
        catalog.add("Goodbye", "", context="menu:y:title")
        for message in catalog:
            if message.id == "Hello":
                message.user_comments = [machine_translation("engine-a")]
        self.path = catalog_path(self.root, "de", "core")
        self.path.parent.mkdir(parents=True)
        write_catalog(self.path, catalog)
        self.asked: dict[tuple[str, ...], tuple[str, ...]] = {}

    def _translate(self, texts, code, exclude=()):
        self.asked[tuple(texts)] = tuple(exclude)
        return Outcome(
            [f"DE {text}" for text in texts], 0, 0, "", ("engine-b",) * len(texts)
        )

    def _judge_and_translate(self) -> None:
        failed = {("menu:x:title", "Hello", "Hallo Welt")}
        self.assertEqual(record_judged(self.root, "core", "de", failed), 1)
        client = mock.Mock()
        client.translate.side_effect = self._translate
        with (
            mock.patch.object(cli, "PROJECT_ROOT", self.root),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            cli.one_catalog(client, self.root, "core", "de")

    def _entry(self, msgid: str):
        return next(m for m in read_catalog(self.path) if m.id == msgid)

    def test_the_failed_engine_is_excluded_from_its_retranslation(self) -> None:
        self._judge_and_translate()

        self.assertEqual(self.asked, {("Hello",): ("engine-a",), ("Goodbye",): ()})

    def test_the_retranslation_keeps_the_failure_on_record(self) -> None:
        self._judge_and_translate()

        hello = self._entry("Hello")
        self.assertEqual(hello.string, "DE Hello")
        self.assertIn(judge_failure("engine-a"), hello.user_comments)
        self.assertIn(machine_translation("engine-b"), hello.user_comments)
        self.assertNotIn(machine_translation("engine-a"), hello.user_comments)

    def test_a_verdict_on_a_translation_since_replaced_is_dropped(self) -> None:
        stale = {("menu:x:title", "Hello", "Hallo")}

        self.assertEqual(record_judged(self.root, "core", "de", stale), 0)
        self.assertEqual(self._entry("Hello").string, "Hallo Welt")


def _role(case: unittest.TestCase) -> Path:
    """Return a custom role directory holding the English source of ``team``.

    Args:
        case: the test whose lifetime the temporary directory follows.
    """
    tmp = TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    role = Path(tmp.name)
    (role / "locale").mkdir()
    (role / "locale" / "team.yml").write_text("title: The team\n", encoding="utf-8")
    return role


def _role_catalog(role: Path, code: str, translation: str) -> None:
    catalog = new_catalog("team", code)
    catalog.add("The team", translation, context="team:title")
    path = catalog_path(role, code, "team")
    path.parent.mkdir(parents=True)
    write_catalog(path, catalog)


class TestRoot(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _checkout(self)
        self.role = _role(self)

    def test_extract_writes_one_catalog_per_language_into_the_role(self) -> None:
        with (
            mock.patch.object(cli, "PROJECT_ROOT", self.root),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            status = cli.extract(["team"], self.role)

        self.assertEqual(status, 0)
        for code in ("de", "fr", "zu"):
            with self.subTest(code=code):
                catalog = read_catalog(catalog_path(self.role, code, "team"))
                self.assertEqual(
                    [(m.context, m.id) for m in catalog if m.id],
                    [("team:title", "The team")],
                )

    def test_extract_with_a_root_leaves_core_catalogs_alone(self) -> None:
        with (
            mock.patch.object(cli, "PROJECT_ROOT", self.root),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            cli.extract(["team"], self.role)

        self.assertFalse((self.root / "locale").exists())

    def _translate(self, root: Path | None) -> int:
        client = mock.Mock()
        client.return_value.translate.side_effect = lambda texts, _code, exclude=(): (
            Outcome(["Das Team"] * len(texts), 0, 0, "")
        )
        with (
            mock.patch.object(cli, "PROJECT_ROOT", self.root),
            mock.patch.object(
                cli,
                "server",
                mock.Mock(return_value=contextlib.nullcontext("http://lt")),
            ),
            mock.patch.object(cli, "LibreTranslate", client),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            return cli.translate(["team"] if root else ["core"], [], False, root)

    def test_translate_fills_the_role_catalog_and_not_core(self) -> None:
        _role_catalog(self.role, "de", "")
        _catalog(self.root, "de", "")

        self.assertEqual(self._translate(self.role), 0)

        role_de = read_catalog(catalog_path(self.role, "de", "team"))
        core_de = read_catalog(catalog_path(self.root, "de", "core"))
        self.assertEqual(
            role_de.get("The team", context="team:title").string, "Das Team"
        )
        self.assertEqual(core_de.get("Hello", context="menu:x:title").string, "")

    def test_translate_without_a_root_leaves_the_role_catalog_alone(self) -> None:
        _role_catalog(self.role, "de", "")
        _catalog(self.root, "de", "")

        self.assertEqual(self._translate(None), 0)

        role_de = read_catalog(catalog_path(self.role, "de", "team"))
        self.assertEqual(role_de.get("The team", context="team:title").string, "")


class TestScope(unittest.TestCase):
    def setUp(self) -> None:
        self.role = _role(self)
        self.parser = argparse.ArgumentParser()

    def _refused(self, root: str, domain: str | None) -> None:
        with (
            mock.patch("sys.stderr", new_callable=io.StringIO),
            self.assertRaises(SystemExit),
        ):
            cli.scope(self.parser, root, domain)

    def test_without_a_root_both_core_domains_are_covered(self) -> None:
        self.assertEqual(cli.scope(self.parser, "", None), (["core", "docs"], None))

    def test_without_a_root_only_core_domains_are_accepted(self) -> None:
        self._refused("", "team")

    def test_a_root_names_its_one_domain(self) -> None:
        self.assertEqual(
            cli.scope(self.parser, str(self.role), "team"),
            (["team"], self.role.resolve()),
        )

    def test_a_root_without_a_domain_is_refused(self) -> None:
        self._refused(str(self.role), None)

    def test_a_domain_that_walks_out_of_locale_is_refused(self) -> None:
        self._refused(str(self.role), "../core")

    def test_a_root_that_is_no_directory_is_refused(self) -> None:
        self._refused(str(self.role / "missing"), "team")


if __name__ == "__main__":
    unittest.main()
