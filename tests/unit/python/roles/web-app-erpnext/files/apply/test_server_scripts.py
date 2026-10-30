from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/server_scripts.py"


class TestServerScripts(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.sites = Path(tmp.name)
        self.config = self.sites / "common_site_config.json"

    def _seed(self, **config) -> None:
        self.config.write_text(json.dumps({"redis_cache": "redis://cache", **config}))

    def _run(self, enabled: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-"],
            input=read_text(str(SCRIPT)),
            cwd=self.sites,
            env={**os.environ, "SERVER_SCRIPTS_ENABLED": enabled},
            capture_output=True,
            text=True,
            check=False,
        )

    def _stored(self) -> dict:
        text = self.config.read_text()  # nocheck: cache-read tempdir fixture
        return json.loads(text)

    def test_enables_as_the_integer_one_and_keeps_other_keys(self) -> None:
        self._seed()

        result = self._run("true")

        self.assertEqual(json.loads(result.stdout), {"changed": True})
        self.assertEqual(self._stored()["server_script_enabled"], 1)
        self.assertEqual(self._stored()["redis_cache"], "redis://cache")

    def test_disables_a_value_bench_stored_as_a_string(self) -> None:
        self._seed(server_script_enabled="1")

        result = self._run("false")

        self.assertEqual(json.loads(result.stdout), {"changed": True})
        self.assertIs(type(self._stored()["server_script_enabled"]), int)
        self.assertEqual(self._stored()["server_script_enabled"], 0)

    def test_rewrites_the_string_zero_that_frappe_reads_as_enabled(self) -> None:
        self._seed(server_script_enabled="0")

        result = self._run("false")

        self.assertEqual(json.loads(result.stdout), {"changed": True})
        self.assertEqual(self._stored()["server_script_enabled"], 0)

    def test_an_aligned_value_is_left_untouched(self) -> None:
        self._seed(server_script_enabled=1)
        before = self.config.read_bytes()  # nocheck: cache-read tempdir fixture

        result = self._run("true")

        self.assertEqual(json.loads(result.stdout), {"changed": False})
        after = self.config.read_bytes()  # nocheck: cache-read tempdir fixture
        self.assertEqual(after, before)

    def test_accepts_the_capitalised_bool_ansible_renders(self) -> None:
        self._seed(server_script_enabled=0)

        result = self._run("True")

        self.assertEqual(json.loads(result.stdout), {"changed": True})
        self.assertEqual(self._stored()["server_script_enabled"], 1)

    def test_an_undeclared_switch_value_fails(self) -> None:
        self._seed()

        result = self._run("yes")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("server_script_enabled", self._stored())


if __name__ == "__main__":
    unittest.main()
