import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

SCRIPT = PROJECT_ROOT / "roles/web-app-mediawiki/files/shell/realign_admin_password.sh"
STATE_SQL = PROJECT_ROOT / "roles/web-app-mediawiki/files/sql/admin_state.sql"
NAME = "platformadmin"
PASSWORD = "the-declared-password"
EMAIL = "platformadmin@example.org"
CREATED = "wikidb: Creating and promoting User:Platformadmin into sysop, bureaucrat...\ndone.\n"
PROMOTED = "wikidb: Promoting User:Platformadmin into sysop, bureaucrat...\ndone."

STUB_PHP = """#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[1] == "sql":
    print("stdClass Object\\n(\\n    [state] => " + os.environ["STUB_STATE"] + "\\n)")
elif "--force" in args:
    print(os.environ["STUB_PROMOTE_OUTPUT"])
else:
    print(os.environ["STUB_CREATE_OUTPUT"], end="")
"""


def _calls(log: Path) -> list[list[str]]:
    return [
        json.loads(line)
        for line in log.read_text().splitlines()  # nocheck: cache-read tempdir fixture
    ]


class TestRealignAdminPassword(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.log = root / "calls.jsonl"
        self.log.touch()
        self.bin = root / "bin"
        self.bin.mkdir()
        stub = self.bin / "php"
        stub.write_text(STUB_PHP.format(python=sys.executable))
        stub.chmod(0o755)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(
        self, state: str, local_login: bool, promote_output: str, email: str
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(self.log),
            "STUB_STATE": state,
            "STUB_PROMOTE_OUTPUT": promote_output,
            "STUB_CREATE_OUTPUT": CREATED,
            "MEDIAWIKI_HTML_DIR": "/var/www/html",
            "MEDIAWIKI_ADMIN_NAME": NAME,
            "MEDIAWIKI_ADMIN_PASSWORD": PASSWORD,
            "MEDIAWIKI_ADMIN_EMAIL": email,
            "MEDIAWIKI_LOCAL_LOGIN": "true" if local_login else "false",
            "MEDIAWIKI_ADMIN_STATE_SQL": read_text(str(STATE_SQL)),
        }
        return subprocess.run(
            ["sh", "-s"],
            input=read_text(str(SCRIPT)),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def _promotions(self) -> list[list[str]]:
        return [call for call in _calls(self.log) if call[1] == "createAndPromote"]

    def test_absent_account_under_sso_is_left_to_the_first_sso_login(self) -> None:
        result = self._run("absent", False, "", EMAIL)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[UNCHANGED]", result.stdout)
        self.assertIn("provisioned by SSO", result.stdout)
        self.assertEqual(self._promotions(), [])

    def test_absent_account_with_local_login_is_created_with_password_and_email(
        self,
    ) -> None:
        result = self._run("absent", True, "", EMAIL)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[CHANGED]", result.stdout)
        self.assertEqual(
            self._promotions(),
            [
                [
                    "/var/www/html/maintenance/run.php",
                    "createAndPromote",
                    "--bureaucrat",
                    "--sysop",
                    "--email",
                    EMAIL,
                    NAME,
                    PASSWORD,
                ]
            ],
        )

    def test_present_sysop_is_realigned_with_force_and_the_password(self) -> None:
        result = self._run("admin", True, "Password set.\ndone.", EMAIL)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[CHANGED]", result.stdout)
        self.assertEqual(
            self._promotions()[0][2:],
            ["--force", "--bureaucrat", "--sysop", NAME, PASSWORD],
        )

    def test_present_sysop_under_sso_is_left_unchanged_without_a_password(
        self,
    ) -> None:
        result = self._run("admin", False, "Account exists and nothing to do.", EMAIL)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[UNCHANGED]", result.stdout)
        self.assertNotIn(PASSWORD, self._promotions()[0])

    def test_wiki_without_any_sysop_fails_without_creating(self) -> None:
        result = self._run("no-admin", True, "", EMAIL)

        self.assertEqual(result.returncode, 1)
        self.assertIn("[FAIL]", result.stderr)
        self.assertIn("no sysop", result.stderr)
        self.assertEqual(self._promotions(), [])

    def test_wiki_without_any_sysop_fails_under_sso_too(self) -> None:
        result = self._run("no-admin", False, "", EMAIL)

        self.assertEqual(result.returncode, 1)
        self.assertIn("no sysop", result.stderr)

    def test_email_held_by_another_account_fails_naming_the_holder(self) -> None:
        result = self._run("email-held:Someone, Other", True, "", EMAIL)

        self.assertEqual(result.returncode, 1)
        self.assertIn("[FAIL]", result.stderr)
        self.assertIn("Someone, Other", result.stderr)
        self.assertEqual(self._promotions(), [])

    def test_sso_account_with_the_confirmed_declared_email_is_promoted(self) -> None:
        result = self._run("not-admin:match", False, PROMOTED, EMAIL)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            f"[CHANGED] promoted {NAME} (SSO account, email matches)",
        )
        self.assertEqual(
            self._promotions(),
            [
                [
                    "/var/www/html/maintenance/run.php",
                    "createAndPromote",
                    "--force",
                    "--bureaucrat",
                    "--sysop",
                    NAME,
                ]
            ],
        )

    def test_matching_account_is_not_promoted_while_local_login_is_on(self) -> None:
        result = self._run("not-admin:match", True, PROMOTED, EMAIL)

        self.assertEqual(result.returncode, 1)
        self.assertIn("not promoted (local login is on)", result.stderr)
        self.assertEqual(self._promotions(), [])

    def test_sso_account_with_another_email_is_not_promoted(self) -> None:
        result = self._run("not-admin:mismatch", False, PROMOTED, EMAIL)

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"its email differs from {EMAIL}", result.stderr)
        self.assertEqual(self._promotions(), [])

    def test_sso_account_with_an_unconfirmed_email_is_not_promoted(self) -> None:
        result = self._run("not-admin:unconfirmed", False, PROMOTED, EMAIL)

        self.assertEqual(result.returncode, 1)
        self.assertIn("is not confirmed", result.stderr)
        self.assertEqual(self._promotions(), [])

    def test_probe_without_a_state_fails(self) -> None:
        result = self._run("", True, "", EMAIL)

        self.assertEqual(result.returncode, 1)
        self.assertIn("returned no state", result.stderr)
        self.assertEqual(self._promotions(), [])

    def test_declared_values_reach_the_probe_only_hex_encoded(self) -> None:
        email = "o'brien@example.org"

        self._run("admin", False, "Account exists and nothing to do.", email)

        query = _calls(self.log)[0][3]
        self.assertNotIn("o'brien", query)
        self.assertIn(email.encode().hex(), query)
        self.assertIn(NAME.encode().hex(), query)
        self.assertNotIn("%(", query)

    def test_empty_state_query_fails_before_any_call(self) -> None:
        result = subprocess.run(
            ["sh", "-s"],
            input=read_text(str(SCRIPT)),
            capture_output=True,
            text=True,
            env={
                "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "STUB_LOG": str(self.log),
                "MEDIAWIKI_HTML_DIR": "/var/www/html",
                "MEDIAWIKI_ADMIN_NAME": NAME,
                "MEDIAWIKI_ADMIN_EMAIL": EMAIL,
            },
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("MEDIAWIKI_ADMIN_STATE_SQL is empty", result.stderr)
        self.assertEqual(_calls(self.log), [])


if __name__ == "__main__":
    unittest.main()
