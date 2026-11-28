import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

SCRIPT = PROJECT_ROOT / "roles/web-app-jitsi/files/shell/realign_accounts.sh"
DOMAIN = "auth.meet.jitsi"
ACCOUNTS = ("focus", "jvb", "jigasi", "jibri")
DECLARED = {
    "focus": "focus-secret",
    "jvb": "jvb-secret",
    "jigasi": "jigasi-secret",
    "jibri": "jibri-secret",
}

PROSODYCTL_STUB = """#!{python}
import hashlib
import os
import re
import sys
from pathlib import Path

store = Path(os.environ["STUB_ACCOUNTS"])
log = Path(os.environ["STUB_LOG"])
args = sys.argv[sys.argv.index("shell") + 1:]


def record(entry):
    with log.open("a", encoding="utf-8") as handle:
        handle.write(entry + "\\n")


def digest(password):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), b"accounts", 4096
    ).hex()


if len(args) == 1 and args[0].startswith(">"):
    host, user, password = (
        bytes.fromhex(value).decode("utf-8")
        for value in re.findall(
            r'^> prosody\\.hosts\\[\\(\\("([0-9a-f]*)"\\).*\\]\\.users\\.test_password'
            r'\\(\\(\\("([0-9a-f]*)"\\).*, \\(\\("([0-9a-f]*)"\\).*\\)$',
            args[0],
        )[0]
    )
    account = store / f"{{user}}@{{host}}"
    record(f"test {{user}}@{{host}}")
    if account.is_file() and account.read_text(encoding="utf-8") == digest(password):
        print("Result: true")
        sys.exit(0)
    print("Error: Auth failed. Invalid username or password.", file=sys.stderr)
    sys.exit(1)

section, action, jid, password = args
account = store / jid
record(f"{{action}} {{jid}}")
if action == "password":
    if not account.is_file():
        print("Error: No such user", file=sys.stderr)
        sys.exit(1)
    account.write_text(digest(password), encoding="utf-8")
    print("OK: User password changed")
    sys.exit(0)
if action == "create":
    if account.is_file():
        print("Error: User exists", file=sys.stderr)
        sys.exit(1)
    account.write_text(digest(password), encoding="utf-8")
    print("OK: User created")
    sys.exit(0)
sys.exit(2)
"""


def digest(password):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), b"accounts", 4096
    ).hex()


class TestRealignAccounts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = root / "accounts"
        self.store.mkdir()
        self.log = root / "prosodyctl.log"
        self.log.touch()
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "prosodyctl"
        stub.write_text(PROSODYCTL_STUB.format(python=sys.executable))
        stub.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB_ACCOUNTS": str(self.store),
            "STUB_LOG": str(self.log),
            "JITSI_REALIGN_AUTH_DOMAIN": DOMAIN,
            **{
                f"JITSI_REALIGN_{user.upper()}_PASSWORD": password
                for user, password in DECLARED.items()
            },
        }

    def plant(self, **passwords):
        for user, password in passwords.items():
            (self.store / f"{user}@{DOMAIN}").write_text(
                digest(password), encoding="utf-8"
            )

    def realign(self, **env):
        done = subprocess.run(
            ["sh", "-s"],
            input=read_text(str(SCRIPT)),
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def writes(self):
        text = self.log.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        return [call for call in text.splitlines() if not call.startswith("test ")]

    def stored(self, user):
        account = self.store / f"{user}@{DOMAIN}"
        return account.read_text(encoding="utf-8")  # nocheck: cache-read tempdir

    def test_accounts_that_already_carry_the_declared_password_are_not_rewritten(self):
        self.plant(**DECLARED)
        done = self.realign()
        self.assertEqual(self.writes(), [])
        self.assertNotIn("[CHANGED]", done.stdout)

    def test_only_the_stale_account_is_rewritten(self):
        self.plant(**{**DECLARED, "focus": "stale"})
        done = self.realign()
        self.assertEqual(self.writes(), [f"password focus@{DOMAIN}"])
        self.assertEqual(self.stored("focus"), digest(DECLARED["focus"]))
        self.assertEqual(done.stdout.count("[CHANGED]"), 1)

    def test_missing_accounts_are_registered_with_the_declared_password(self):
        done = self.realign()
        for user in ACCOUNTS:
            self.assertEqual(self.stored(user), digest(DECLARED[user]))
        self.assertEqual(done.stdout.count("[CHANGED]"), len(ACCOUNTS))

    def test_a_password_with_lua_and_shell_metacharacters_verifies_unchanged(self):
        awkward = "q\"'\\]]==]%s $(x) `y` ümlaut"
        self.plant(**{**DECLARED, "jvb": awkward})
        self.realign(JITSI_REALIGN_JVB_PASSWORD=awkward)
        self.assertEqual(self.writes(), [])

    def test_an_empty_declared_password_fails(self):
        done = subprocess.run(
            ["sh", "-s"],
            input=read_text(str(SCRIPT)),
            env={**self.env, "JITSI_REALIGN_FOCUS_PASSWORD": ""},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("[FAIL]", done.stderr)


if __name__ == "__main__":
    unittest.main()
