from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_DIR = importlib.import_module(
    "tests.unit.python.roles.web-app-semaphore.files._semaphore_fake"
).PYTHON_DIR
PACKAGE = ("cli", "administration", "deploy", "dedicated")
STUB = """import json, os
from pathlib import Path


class OpenBaoPreflightError(Exception):
    pass


def prepare(inventory, environ):
    Path(os.environ["STUB_PREPARE"]).write_text(json.dumps(inventory))
    if os.environ.get("STUB_REFUSE"):
        raise OpenBaoPreflightError("the reference tenant/data/ws-x/key is missing")
    environ["BAO_TOKEN"] = "s.stubtoken"
    return 0
"""
PLAY = (
    "import json, os, sys; from pathlib import Path; "
    "Path(os.environ['STUB_PLAY']).write_text(json.dumps("
    "{'argv': sys.argv[1:], 'token': 'BAO_TOKEN' in os.environ}))"
)


class BaoPreflightTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.tmp = Path(scratch.name)
        package = self.tmp.joinpath("src", *PACKAGE)
        package.mkdir(parents=True)
        for depth in range(1, len(PACKAGE) + 1):
            self.tmp.joinpath("src", *PACKAGE[:depth], "__init__.py").touch()
        (package / "openbao.py").write_text(STUB, encoding="utf-8")
        self.prepared = self.tmp / "prepare.json"
        self.played = self.tmp / "play.json"

    def run_preflight(self, args, refuse=False):
        env = {
            "PATH": os.environ["PATH"],
            "INFINITO_SRC_DIR": str(self.tmp / "src"),
            "STUB_PREPARE": str(self.prepared),
            "STUB_PLAY": str(self.played),
        }
        if refuse:
            env["STUB_REFUSE"] = "1"
        return subprocess.run(
            [sys.executable, str(PYTHON_DIR / "bao" / "preflight.py"), *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_the_play_runs_with_the_token_after_the_preflight(self):
        run = self.run_preflight(
            ["inventory/devices.yml", sys.executable, "-c", PLAY, "--limit", "host"]
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        prepared = self.prepared.read_text()  # nocheck: cache-read tempdir
        played = self.played.read_text()  # nocheck: cache-read tempdir
        self.assertEqual(json.loads(prepared), "inventory/devices.yml")
        self.assertEqual(
            json.loads(played),
            {"argv": ["--limit", "host"], "token": True},
        )

    def test_a_refused_preflight_never_runs_the_play(self):
        run = self.run_preflight(
            ["inventory/devices.yml", sys.executable, "-c", PLAY], refuse=True
        )
        self.assertEqual(run.returncode, 1)
        self.assertIn(
            "bao/preflight.py: the reference tenant/data/ws-x/key is missing",
            run.stderr,
        )
        self.assertTrue(self.prepared.exists())
        self.assertFalse(self.played.exists())

    def test_a_command_line_without_the_play_is_refused_before_the_preflight(self):
        run = self.run_preflight(["inventory/devices.yml"])
        self.assertEqual(run.returncode, 2)
        self.assertIn(
            "bao/preflight.py: expects the inventory and the play", run.stderr
        )
        self.assertFalse(self.prepared.exists())

    def test_the_stub_keeps_the_interface_of_the_real_preflight(self):
        real = importlib.import_module(".".join((*PACKAGE, "openbao")))
        self.assertTrue(callable(real.prepare))
        self.assertTrue(issubclass(real.OpenBaoPreflightError, Exception))


if __name__ == "__main__":
    unittest.main()
