from __future__ import annotations

import os
import tempfile
import unittest.mock
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

import cli.contributing.update.apps.__main__ as apps

REPO = "infinito-nexus/core"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
)
TRUNCATED_KEY = b"\n".join([*KEY.splitlines()[:2], KEY.splitlines()[-1]]) + b"\n"
EC_KEY = ec.generate_private_key(ec.SECP256R1()).private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
BRANCH_MAIN = "branch:main\n"
NOW = 1_800_000_000.0
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
            "",
            str(self.updater_pem),
            UPDATER_ID,
            "y",
            "",
            "",
            str(self.translate_pem),
            TRANSLATE_ID,
            "y",
            "y",
            "y",
        ]

    def test_keys_reach_gh_through_stdin_only(self) -> None:
        gh = FakeGh("updater\n", BRANCH_MAIN, "")
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
        gh = FakeGh("updater\n", "branch:main\nbranch:feature/*\n", "")
        with self.assertRaises(SystemExit):
            self.run_main(gh, self.full_answers())
        self.assertEqual(gh.secrets_set(), [])

    def test_tag_policy_named_main_stops_before_any_secret(self) -> None:
        gh = FakeGh("updater\n", "tag:main\n", "")
        with self.assertRaises(SystemExit):
            self.run_main(gh, self.full_answers())
        self.assertEqual(gh.secrets_set(), [])

    def test_file_without_usable_rsa_key_stops_before_any_secret(self) -> None:
        for body in (b"not a key", TRUNCATED_KEY, EC_KEY):
            with self.subTest(body=body[:30]):
                self.updater_pem.write_bytes(body)
                gh = FakeGh("updater\n", BRANCH_MAIN, "")
                with self.assertRaises(SystemExit):
                    self.run_main(gh, self.full_answers())
                self.assertEqual(gh.secrets_set(), [])

    def test_unconfirmed_old_key_deletion_stops_before_translation(self) -> None:
        gh = FakeGh("updater\n", BRANCH_MAIN, "")
        answers = ["", str(self.updater_pem), UPDATER_ID, "n"]
        with self.assertRaises(SystemExit):
            self.run_main(gh, answers)
        self.assertEqual(
            [n for n, _, _ in gh.secrets_set()],
            ["BOT_APP_CLIENT_ID", "BOT_APP_PRIVATE_KEY"],
        )

    def test_repository_copies_of_the_updater_key_are_deleted(self) -> None:
        gh = FakeGh("updater\n", BRANCH_MAIN, "BOT_APP_PRIVATE_KEY\nDOCKERHUB_TOKEN\n")
        answers = ["", "", str(self.translate_pem), TRANSLATE_ID, "y", "n"]
        self.run_main(gh, answers, "--skip-updater")
        deleted = [a[2] for a, _ in gh.calls if a[:2] == ["secret", "delete"]]
        self.assertEqual(deleted, ["BOT_APP_PRIVATE_KEY"])
        self.assertTrue(self.translate_pem.exists())

    def test_client_id_must_be_an_app_client_id(self) -> None:
        gh = FakeGh("updater\n", BRANCH_MAIN, "")
        with self.assertRaises(SystemExit):
            self.run_main(gh, ["", str(self.updater_pem), "12345"])
        self.assertEqual(gh.secrets_set(), [])

    def test_downloads_offers_only_the_key_generated_during_the_step(self) -> None:
        downloads = self.tmp / "downloads"
        downloads.mkdir()
        stale = downloads / "old.pem"
        stale.write_bytes(b"stale")
        os.utime(stale, (NOW - 1, NOW - 1))
        fresh = downloads / "infinito-nexus-updater.private-key.pem"
        replies = iter(["", UPDATER_ID, "n"])
        prompts: list[str] = []

        def ask(prompt: str) -> str:
            prompts.append(prompt)
            if "Press Enter when done" in prompt:
                fresh.write_bytes(KEY)
                os.utime(fresh, (NOW + 1, NOW + 1))
            return next(replies)

        gh = FakeGh("updater\n", BRANCH_MAIN, "")
        with (
            unittest.mock.patch.object(apps.time, "time", return_value=NOW),
            self.assertRaises(SystemExit),
        ):
            apps.main(
                [
                    "--repo",
                    REPO,
                    "--updater-slug",
                    "infinito-nexus-updater",
                    "--translate-slug",
                    "infinito-nexus-translator",
                    "--downloads",
                    str(downloads),
                ],
                gh=gh,
                ask=lambda p: "" if "use it" in p else ask(p),
                say=self.said.append,
            )
        self.assertIn(f"   Found the new key {fresh}", self.said)
        self.assertEqual(gh.secrets_set()[1], ("BOT_APP_PRIVATE_KEY", "updater", KEY))


if __name__ == "__main__":
    unittest.main()
