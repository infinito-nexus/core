from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_DIR = importlib.import_module(
    "tests.unit.python.roles.web-app-semaphore.files._semaphore_fake"
).PYTHON_DIR
STUB = """import json, os
from pathlib import Path


class OpenBaoError(Exception):
    pass


class Client:
    token = "s.tasktoken"


def login(environ):
    Path(os.environ["STUB_RECORD"]).write_text(json.dumps(sorted(environ)))
    if os.environ.get("STUB_REFUSE"):
        raise OpenBaoError("OpenBao refused the task token login to auth/jwt role members (HTTP 403)")
    return Client()
"""
TASK = {
    "BAO_ADDR": "https://openbao.example.org",
    "BAO_CACERT": "/etc/ssl/certs/infinito-ca.pem",
    "BAO_ROLE": "members",
    "SEMAPHORE_JWT": "header.claims.signature",
}


class BaoLoginTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.tmp = Path(scratch.name)
        utils = self.tmp / "src" / "utils"
        utils.mkdir(parents=True)
        (utils / "__init__.py").write_text("", encoding="utf-8")
        (utils / "openbao_client.py").write_text(STUB, encoding="utf-8")
        self.record = self.tmp / "record.json"
        self.token = self.tmp / "bao-token"

    def run_login(self, **extra):
        env = {
            "PATH": "/usr/bin:/bin",
            "INFINITO_SRC_DIR": str(self.tmp / "src"),
            "STUB_RECORD": str(self.record),
            "BAO_TOKEN": "s.operatortoken",
            **TASK,
            **extra,
        }
        return subprocess.run(
            [
                sys.executable,
                "-I",
                str(PYTHON_DIR / "bao" / "login.py"),
                str(self.token),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_the_wrapper_logs_in_with_the_task_token_only(self):
        run = self.run_login()
        self.assertEqual(run.returncode, 0, run.stderr)
        recorded = self.record.read_text()  # nocheck: cache-read tempdir
        self.assertEqual(json.loads(recorded), sorted(TASK))
        token = self.token.read_text()  # nocheck: cache-read tempdir
        self.assertEqual(token, "s.tasktoken")
        self.assertEqual(self.token.stat().st_mode & 0o777, 0o600)
        self.assertEqual(run.stdout, "")

    def test_a_refused_login_writes_no_token(self):
        run = self.run_login(STUB_REFUSE="1")
        self.assertEqual(run.returncode, 1)
        self.assertIn("bao/login.py: OpenBao refused", run.stderr)
        self.assertFalse(self.token.exists())


if __name__ == "__main__":
    unittest.main()
