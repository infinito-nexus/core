import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

ENTRYPOINT = PROJECT_ROOT / "roles/web-app-lam/files/shell/entrypoint.sh"
CONFIG_DIR = "/var/lib/ldap-account-manager/config"
SERVED_PROFILE = f"{CONFIG_DIR}/lam.conf"
SAMPLE_PROFILE = f"{CONFIG_DIR}/unix.sample.conf"
PATCHER = "/usr/local/share/infinito-lam/login_search.php"

PHP_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "${STUB_PHP_LOG}"
"""


class TestLamEntrypoint(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "php"
        stub.write_text(PHP_STUB)
        stub.chmod(0o755)
        self.php_log = root / "php.log"
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB_PHP_LOG": str(self.php_log),
            "LAM_LOGIN_SEARCH_SUFFIX": "ou=users,dc=example,dc=test",
            "LAM_LOGIN_SEARCH_FILTER": "(uid=%USER%)",
        }

    def patcher_args(self):
        subprocess.run(
            ["bash", str(ENTRYPOINT)],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        log = self.php_log.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        return log.splitlines()

    def test_the_patcher_gets_the_served_profile_then_the_sample_profile(self):
        self.assertEqual(
            self.patcher_args(),
            [PATCHER, SERVED_PROFILE, SAMPLE_PROFILE],
            "the LAM image ships lam.conf and start.sh copies unix.sample.conf only while "
            "lam.conf is missing, so the search login must be written into lam.conf itself "
            "and into the sample a missing lam.conf is copied from",
        )


if __name__ == "__main__":
    unittest.main()
