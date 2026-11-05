import contextlib
import io
import json
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-peertube"
SCRIPT = ROLE / "files" / "python" / "rbac" / "sync.py"
SQL_DIR = ROLE / "files" / "sql" / "rbac"
SQL_FILES = ("link-preprovisioned-accounts.sql", "reconcile-roles.sql")
ROLE_IDS = {"administrator": 0, "moderator": 1, "user": 2}


def load_module():
    module = types.ModuleType("peertube_rbac_sync")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


class FakeDatabase:
    def __init__(self, linked, reconcile_output):
        self.linked = linked
        self.reconcile_output = reconcile_output
        self.runs = []

    def __call__(self, argv, **kwargs):
        script = kwargs["input"]
        forwarded = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-e"]
        self.runs.append((script, forwarded, kwargs["env"]))
        if 'SET "pluginAuth"' in script:
            stdout = "".join(f"{username}\n" for username in self.linked)
        else:
            stdout = self.reconcile_output
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


class PeertubeRbacSyncTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.workdir = tempfile.TemporaryDirectory()
        for name in SQL_FILES:
            (Path(self.workdir.name) / name).write_text(
                read_text(str(SQL_DIR / name)), encoding="utf-8"
            )
        self.previous = Path.cwd()
        os.chdir(self.workdir.name)

    def tearDown(self):
        os.chdir(self.previous)
        self.workdir.cleanup()

    def environ(self):
        return {
            "RBAC_SYNC_CONTAINER_BIN": "/usr/bin/container",
            "RBAC_SYNC_CID": "db1",
            "PGPASSWORD": "pg-secret",
            "PEERTUBE_DB_USER": "peertube",
            "PEERTUBE_DB_NAME": "peertube",
            "PEERTUBE_ROOT_USERNAME": "root",
            "PEERTUBE_RBAC_ROLE_IDS": json.dumps(ROLE_IDS),
            "PEERTUBE_OIDC_PLUGIN": "peertube-plugin-auth-openid-connect",
            "RBAC_MEMBERS": json.dumps({"administrator": [], "moderator": []}),
        }

    def run_main(self, database):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(self.environ(), run=database)
        return stdout.getvalue().strip().splitlines()

    def test_linked_accounts_and_role_changes_are_reported(self):
        output = self.run_main(FakeDatabase(["bob"], "CHANGED bob role=1\n"))

        self.assertEqual(output, ["CHANGED bob linked", "CHANGED bob role=1"])

    def test_nothing_to_link_or_change_is_unchanged(self):
        output = self.run_main(FakeDatabase([], "UNCHANGED\n"))

        self.assertEqual(output, ["UNCHANGED"])

    def test_every_run_is_psql_in_the_database_container(self):
        database = FakeDatabase([], "UNCHANGED\n")
        self.run_main(database)

        self.assertEqual(2, len(database.runs))
        self.assertEqual(
            [forwarded for _, forwarded, _ in database.runs],
            [
                [
                    "PGPASSWORD",
                    "PEERTUBE_OIDC_PLUGIN",
                    "PEERTUBE_ROOT_USERNAME",
                    "RBAC_MEMBERS",
                ],
                [
                    "PGPASSWORD",
                    "RBAC_MEMBERS",
                    "PEERTUBE_RBAC_ROLE_IDS",
                    "PEERTUBE_OIDC_PLUGIN",
                ],
            ],
        )
        for script, forwarded, _ in database.runs:
            read = {
                line.split()[2]
                for line in script.splitlines()
                if line.startswith("\\getenv")
            }
            self.assertTrue(
                read <= set(forwarded), f"{read - set(forwarded)} not forwarded"
            )

    def test_the_link_selects_the_accounts_by_group_membership(self):
        """A per-run list of created accounts loses every account a failed run
        created but never linked: it would keep its role and escape demotion."""
        link = read_text(str(SQL_DIR / "link-preprovisioned-accounts.sql"))
        self.assertIn("\\getenv members RBAC_MEMBERS", link)
        self.assertIn("jsonb_each(:'members'::jsonb)", link)
        self.assertNotIn("PEERTUBE_RBAC_CREATED", link)
        self.assertIn('"pluginAuth" IS NULL', link)
        self.assertIn("username <> :'root_username'", link)

    def test_a_used_self_registration_with_a_members_email_is_never_linked(self):
        """mallory registers with carol's e-mail and logs in; carol then joins
        the administrator group. Linking by e-mail alone would hand mallory's
        live account to the plugin and reconcile would make it administrator."""
        link = " ".join(
            read_text(str(SQL_DIR / "link-preprovisioned-accounts.sql")).split()
        )
        self.assertIn('account."lastLoginDate" IS NULL', link)
        self.assertIn(
            'NOT EXISTS ( SELECT 1 FROM public."oAuthToken" AS token WHERE token."userId" = account.id )',
            link,
        )

    def test_the_username_and_the_email_must_match_the_same_member(self):
        """A break-glass admin sharing a moderator's e-mail under another
        username keeps its password login and its role."""
        link = " ".join(
            read_text(str(SQL_DIR / "link-preprovisioned-accounts.sql")).split()
        )
        self.assertIn(
            "WHERE entry->>'username' = account.username AND lower(entry->>'email') = lower(account.email)",
            link,
        )
        self.assertNotIn("lower(email) IN", link)

    def test_a_password_grant_racing_the_link_loses_its_token(self):
        """A grant that read the account before the link committed inserts its
        token after the link's snapshot; the reconcile, a later statement,
        deletes every password-grant token of a plugin account."""
        reconcile = " ".join(read_text(str(SQL_DIR / "reconcile-roles.sql")).split())
        self.assertIn(
            'DELETE FROM public."oAuthToken" AS token USING public."user" AS account '
            'WHERE token."userId" = account.id AND account."pluginAuth" = :\'plugin\' '
            'AND token."authName" IS NULL',
            reconcile,
        )
        self.assertIn("NOT EXISTS (SELECT 1 FROM revoked)", reconcile)

    def test_revoked_tokens_are_reported_as_changes(self):
        output = self.run_main(
            FakeDatabase([], "CHANGED mallory password tokens revoked\n")
        )

        self.assertEqual(["CHANGED mallory password tokens revoked"], output)

    def test_the_hook_holds_no_http_channel(self):
        source = read_text(str(SCRIPT))
        self.assertNotIn("urllib", source)
        self.assertNotIn("PEERTUBE_URL", source)
        self.assertNotIn("PEERTUBE_ROOT_PASSWORD", source)


if __name__ == "__main__":
    unittest.main()
