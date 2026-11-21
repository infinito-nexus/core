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

SCRIPT = (
    PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/site_config_revision.py"
)
DECLARED = {
    "db_host": "mariadb",
    "db_port": 3306,
    "redis_cache": "redis://erpnext:old@redis:6379/0",
    "socketio_port": 9000,
}


class TestSiteConfigRevision(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.sites = Path(tmp.name)
        self.config = self.sites / "common_site_config.json"
        self.stamp = self.sites / ".common_site_config.revision"

    def _seed(self, **config) -> None:
        self.config.write_text(json.dumps({"server_script_enabled": 0, **config}))

    def _run(self, declared: dict, record: str) -> dict:
        result = subprocess.run(
            [sys.executable, "-I", "-"],
            input=read_text(str(SCRIPT)),
            cwd=self.sites,
            env={
                **os.environ,
                "DECLARED_CONFIG": json.dumps(declared),
                "RECORD": record,
            },
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_a_site_without_a_stamp_is_restarted_once(self) -> None:
        self._seed(**DECLARED)

        self.assertEqual(
            self._run(DECLARED, "false"), {"applied": True, "current": False}
        )
        self.assertEqual(
            self._run(DECLARED, "True"), {"applied": True, "current": False}
        )
        self.assertEqual(
            self._run(DECLARED, "false"), {"applied": True, "current": True}
        )

    def test_an_unchanged_config_needs_no_restart_and_keeps_the_stamp(self) -> None:
        self._seed(**DECLARED)
        self._run(DECLARED, "true")
        before = self.stamp.read_bytes()  # nocheck: cache-read tempdir fixture

        self.assertEqual(
            self._run(DECLARED, "true"), {"applied": True, "current": True}
        )
        after = self.stamp.read_bytes()  # nocheck: cache-read tempdir fixture
        self.assertEqual(after, before)

    def test_a_rotated_password_is_not_current_until_recorded(self) -> None:
        self._seed(**DECLARED)
        self._run(DECLARED, "true")
        rotated = {**DECLARED, "redis_cache": "redis://erpnext:new@redis:6379/0"}
        self._seed(**rotated)

        self.assertEqual(
            self._run(rotated, "false"), {"applied": True, "current": False}
        )
        self._run(rotated, "true")
        self.assertEqual(
            self._run(rotated, "false"), {"applied": True, "current": True}
        )

    def test_a_config_the_configurator_has_not_written_is_never_recorded(
        self,
    ) -> None:
        self._seed(**DECLARED)
        rotated = {**DECLARED, "redis_cache": "redis://erpnext:new@redis:6379/0"}

        self.assertEqual(
            self._run(rotated, "true"), {"applied": False, "current": False}
        )
        self.assertFalse(self.stamp.exists())

    def test_a_port_declared_as_a_string_matches_the_stored_number(self) -> None:
        self._seed(**DECLARED)
        as_strings = {**DECLARED, "db_port": "3306", "socketio_port": "9000"}
        self._run(DECLARED, "true")

        self.assertEqual(
            self._run(as_strings, "false"), {"applied": True, "current": True}
        )

    def test_an_undeclared_record_value_fails(self) -> None:
        self._seed(**DECLARED)

        with self.assertRaises(subprocess.CalledProcessError):
            self._run(DECLARED, "yes")
        self.assertFalse(self.stamp.exists())


if __name__ == "__main__":
    unittest.main()
