from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cli.contributing.update.apps.__main__ as apps

REPO = "infinito-nexus/core"
KEY = b"-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n"
UPDATER_ID = "Iv23liUpdater01"
TRANSLATE_ID = "Iv23liTranslate1"


class FakeGh:
    def __init__(self, environments: str, policies: str, repo_secrets: str) -> None:
        self.calls: list[tuple[list[str], bytes | None]] = []
        self.outputs = {
            f"repos/{REPO}/environments": environments,
            f"repos/{REPO}/environments/updater/deployment-branch-policies": policies,
        }
        self.repo_secrets = repo_secrets

    def __call__(self, args, stdin):
        self.calls.append((list(args), stdin))
        if args[:2] == ["secret", "list"]:
            return self.repo_secrets.encode()
        if args[0] == "api" and len(args) > 1:
            return self.outputs.get(args[1], "").encode()
        return b""

    def secrets_set(self):
        return [
            (a[2], a[a.index("--env") + 1] if "--env" in a else None, s)
            for a, s in self.calls
            if a[:2] == ["secret", "set"]
        ]


class AppsMainTest(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        self.updater_pem = self.tmp / "updater.pem"
        self.translate_pem = self.tmp / "translate.pem"
        self.updater_pem.write_bytes(KEY)
        self.translate_pem.write_bytes(KEY)
        self.said: list[str] = []

    def run_main(self, gh, answers, *extra):
        replies = iter(answers)
        return apps.main(
            [
                "--repo",
                REPO,
                "--updater-slug",
                "infinito-nexus-updater",
                "--translate-slug",
                "infinito-nexus-translator",
                *extra,
            ],
            gh=gh,
            ask=lambda _prompt: next(replies),
            say=self.said.append,
        )

    def full_answers(self):
        return [
            UPDATER_ID,
            str(self.updater_pem),
            "y",
            "y",
            TRANSLATE_ID,
            str(self.translate_pem),
            "y",
            "y",
        ]

    def test_keys_reach_gh_through_stdin_only(self) -> None:
        gh = FakeGh("updater\n", "main\n", "")
        self.assertEqual(self.run_main(gh, self.full_answers()), 0)
        self.assertEqual(
            gh.secrets_set(),
            [
                ("BOT_APP_CLIENT_ID", "updater", UPDATER_ID.encode()),
                ("BOT_APP_PRIVATE_KEY", "updater", KEY),
                ("TRANSLATE_APP_CLIENT_ID", None, TRANSLATE_ID.encode()),
                ("TRANSLATE_APP_PRIVATE_KEY", None, KEY),
            ],
        )
        for args, _stdin in gh.calls:
            self.assertNotIn(KEY.decode(), " ".join(args))
        self.assertNotIn(KEY.decode(), "\n".join(self.said))
        self.assertFalse(self.updater_pem.exists())
        self.assertFalse(self.translate_pem.exists())

    def test_missing_environment_is_created_main_only(self) -> None:
        gh = FakeGh("auto-merge\n", "", "")
        self.run_main(gh, self.full_answers())
        api = [a for a, _ in gh.calls if a[0] == "api" and "--method" in a]
        self.assertEqual(api[0][2:4], ["PUT", f"repos/{REPO}/environments/updater"])
        self.assertIn("name=main", api[1])

    def test_environment_open_to_other_branches_stops_before_any_secret(self) -> None:
        gh = FakeGh("updater\n", "main\nfeature/*\n", "")
        with self.assertRaises(SystemExit):
            self.run_main(gh, self.full_answers())
        self.assertEqual(gh.secrets_set(), [])

    def test_file_without_private_key_stops_before_any_secret(self) -> None:
        self.updater_pem.write_bytes(b"not a key")
        gh = FakeGh("updater\n", "main\n", "")
        with self.assertRaises(SystemExit):
            self.run_main(gh, self.full_answers())
        self.assertEqual(gh.secrets_set(), [])

    def test_unconfirmed_old_key_deletion_stops_before_translation(self) -> None:
        gh = FakeGh("updater\n", "main\n", "")
        answers = [UPDATER_ID, str(self.updater_pem), "n"]
        with self.assertRaises(SystemExit):
            self.run_main(gh, answers)
        self.assertEqual(
            [n for n, _, _ in gh.secrets_set()],
            ["BOT_APP_CLIENT_ID", "BOT_APP_PRIVATE_KEY"],
        )

    def test_repository_copies_of_the_updater_key_are_deleted(self) -> None:
        gh = FakeGh("updater\n", "main\n", "BOT_APP_PRIVATE_KEY\nDOCKERHUB_TOKEN\n")
        answers = ["y", TRANSLATE_ID, str(self.translate_pem), "n"]
        self.run_main(gh, answers, "--skip-updater")
        deleted = [a[2] for a, _ in gh.calls if a[:2] == ["secret", "delete"]]
        self.assertEqual(deleted, ["BOT_APP_PRIVATE_KEY"])
        self.assertTrue(self.translate_pem.exists())

    def test_client_id_must_be_an_app_client_id(self) -> None:
        gh = FakeGh("updater\n", "main\n", "")
        with self.assertRaises(SystemExit):
            self.run_main(gh, ["12345", str(self.updater_pem)])
        self.assertEqual(gh.secrets_set(), [])


if __name__ == "__main__":
    unittest.main()
