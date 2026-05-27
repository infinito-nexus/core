"""Unit tests for `utils.cleanup.tokens` (token-store wipe helper)."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.cache.yaml import _reset_cache_for_tests, load_yaml_any
from utils.cleanup.tokens import main, wipe_tokens


class TokensTestBase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tokens_file = Path(self._tmp.name) / "tokens.yml"

    def _write(self, content: str) -> None:
        self.tokens_file.write_text(content, encoding="utf-8")


class TestWipeTokens(TokensTestBase, unittest.TestCase):
    def test_removes_matching_entry(self):
        self._write(
            "users:\n"
            "  administrator:\n"
            "    tokens:\n"
            "      web-app-matomo: T1\n"
            "      web-app-keycloak: T2\n"
        )

        removed = wipe_tokens(["web-app-matomo"], tokens_file=self.tokens_file)

        self.assertEqual(removed, ["administrator.web-app-matomo"])
        on_disk = load_yaml_any(str(self.tokens_file))
        self.assertEqual(
            on_disk["users"]["administrator"]["tokens"],
            {"web-app-keycloak": "T2"},
        )

    def test_no_match_does_not_rewrite_file(self):
        self._write(
            "users:\n  administrator:\n    tokens:\n      web-app-keycloak: T2\n"
        )
        before_mtime = self.tokens_file.stat().st_mtime_ns

        removed = wipe_tokens(["web-app-matomo"], tokens_file=self.tokens_file)

        self.assertEqual(removed, [])
        self.assertEqual(self.tokens_file.stat().st_mtime_ns, before_mtime)

    def test_missing_file_returns_empty(self):
        # File never created, .exists() == False.
        removed = wipe_tokens(["web-app-matomo"], tokens_file=self.tokens_file)
        self.assertEqual(removed, [])
        self.assertFalse(self.tokens_file.exists())

    def test_wipes_from_multiple_users(self):
        self._write(
            "users:\n"
            "  administrator:\n"
            "    tokens:\n"
            "      web-app-matomo: T1\n"
            "  ci-bot:\n"
            "    tokens:\n"
            "      web-app-matomo: T9\n"
            "      web-app-keycloak: T2\n"
        )

        removed = wipe_tokens(["web-app-matomo"], tokens_file=self.tokens_file)

        self.assertEqual(
            sorted(removed),
            ["administrator.web-app-matomo", "ci-bot.web-app-matomo"],
        )
        on_disk = load_yaml_any(str(self.tokens_file))
        self.assertEqual(on_disk["users"]["administrator"]["tokens"], {})
        self.assertEqual(
            on_disk["users"]["ci-bot"]["tokens"],
            {"web-app-keycloak": "T2"},
        )

    def test_multiple_app_ids_in_one_call(self):
        self._write(
            "users:\n"
            "  administrator:\n"
            "    tokens:\n"
            "      web-app-matomo: T1\n"
            "      web-app-keycloak: T2\n"
            "      web-app-akaunting: T3\n"
        )

        removed = wipe_tokens(
            ["web-app-matomo", "web-app-akaunting"],
            tokens_file=self.tokens_file,
        )

        self.assertEqual(
            sorted(removed),
            ["administrator.web-app-akaunting", "administrator.web-app-matomo"],
        )
        on_disk = load_yaml_any(str(self.tokens_file))
        self.assertEqual(
            on_disk["users"]["administrator"]["tokens"],
            {"web-app-keycloak": "T2"},
        )

    def test_user_without_tokens_field_is_skipped(self):
        self._write(
            "users:\n"
            "  administrator:\n"
            "    email: admin@example.org\n"
            "  ci-bot:\n"
            "    tokens:\n"
            "      web-app-matomo: T1\n"
        )

        removed = wipe_tokens(["web-app-matomo"], tokens_file=self.tokens_file)

        self.assertEqual(removed, ["ci-bot.web-app-matomo"])

    def test_non_dict_user_entry_is_skipped(self):
        self._write(
            "users:\n"
            "  legacy-string-entry: just-a-string\n"
            "  administrator:\n"
            "    tokens:\n"
            "      web-app-matomo: T1\n"
        )

        removed = wipe_tokens(["web-app-matomo"], tokens_file=self.tokens_file)

        self.assertEqual(removed, ["administrator.web-app-matomo"])


class TestMainShim(TokensTestBase, unittest.TestCase):
    def test_no_argv_prints_usage_and_returns_2(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            rc = main([])
        self.assertEqual(rc, 2)
        self.assertIn("usage:", stderr.getvalue())

    def test_main_uses_default_path_when_no_override(self):
        # With no FILE_TOKENS env var and the default path missing on the
        # test host, main MUST still return 0 and report a no-op.
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main(["web-app-nonexistent"])
        self.assertEqual(rc, 0)
        self.assertIn("No token entries to wipe", stdout.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
