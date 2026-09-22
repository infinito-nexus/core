"""verify/backup.sh owes no dump for a provider nobody on the host consumes.

A database provider deployed without a consumer holds only the databases its
engine creates for itself. No databases.csv row names it, so baudolo copies the
volume live and records it undumped, and the drill failed on data nobody wrote.
Every other undumped database volume, above all one whose consumer forgot to
seed its row, stays a failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.recovery.layout import FILES_DIR, MANIFEST_FILE, MANIFEST_SCHEMA, SQL_DIR

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "svc-bkp-volume-2-local"
    / "files"
    / "test"
    / "verify"
    / "backup.sh"
)
GENERATION = "20260922135655"


def _verify(
    volume: str, engine: str, consumerless: str
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as repo:
        generation = Path(repo) / GENERATION
        files = generation / volume / FILES_DIR
        files.mkdir(parents=True)
        (files / "PG_VERSION").write_text("17", encoding="utf-8")
        (generation / MANIFEST_FILE).write_text(
            json.dumps(
                {
                    "schema": MANIFEST_SCHEMA,
                    "layout": {"files_dir": FILES_DIR, "sql_dir": SQL_DIR},
                    "volumes": {
                        volume: {"database": True, "dumped": False, "engine": engine}
                    },
                }
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "REPO_DIR": repo,
            "NEWEST_GENERATION": GENERATION,
            "BKP_TEST_REPO_ROOT": str(PROJECT_ROOT),
            "BKP_TEST_PYTHON": sys.executable,
            "BKP_TEST_CONSUMERLESS_DB_VOLUMES": consumerless,
        }
        return subprocess.run(
            ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, check=False
        )


class TestVerifyBackup(unittest.TestCase):
    def assert_passes(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("nothing owes a dump", result.stdout)

    def assert_fails(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("but no sql dump", result.stdout)

    def test_an_unconsumed_provider_owes_no_dump(self) -> None:
        self.assert_passes(_verify("postgres_data", "postgres", "postgres_data"))

    def test_a_consumed_provider_owes_a_dump(self) -> None:
        self.assert_fails(_verify("postgres_data", "postgres", ""))

    def test_only_the_named_volume_is_released(self) -> None:
        self.assert_fails(_verify("mariadb_data", "mariadb", "postgres_data"))

    def test_a_name_is_matched_whole_not_as_a_prefix(self) -> None:
        self.assert_fails(_verify("postgres_data", "postgres", "postgres"))


if __name__ == "__main__":
    unittest.main()
