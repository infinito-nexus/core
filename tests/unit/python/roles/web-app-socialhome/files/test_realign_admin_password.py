from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = (
    PROJECT_ROOT / "roles/web-app-socialhome/files/python/realign_admin_password.py"
)
USERNAME = "platform_administrator"
PASSWORD = "the-password-this-deploy-rendered"
PREVIOUS = "the-password-the-last-deploy-rendered"


def load_script() -> object:
    spec = importlib.util.spec_from_file_location("realign_admin_password", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def credentials_module() -> dict:
    platform = types.ModuleType("socialhome.platform")
    credentials = types.ModuleType("socialhome.platform.local_credentials")
    credentials.hash_password = lambda plain: f"scrypt$fake${plain}"
    credentials.verify_password = lambda plain, stored: stored == f"scrypt$fake${plain}"
    return {
        "socialhome": types.ModuleType("socialhome"),
        "socialhome.platform": platform,
        "socialhome.platform.local_credentials": credentials,
    }


class TestRealignAdminPassword(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "socialhome.db")
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "CREATE TABLE platform_users ("
            "username TEXT PRIMARY KEY, display_name TEXT, "
            "is_admin INTEGER, password_hash TEXT)"
        )
        connection.commit()
        connection.close()

    def seed(self, password: str) -> None:
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "INSERT INTO platform_users(username, display_name, is_admin, "
            "password_hash) VALUES(?, ?, 1, ?)",
            (USERNAME, "Admin", f"scrypt$fake${password}"),
        )
        connection.commit()
        connection.close()

    def stored_hash(self) -> str | None:
        connection = sqlite3.connect(self.db_path)
        row = connection.execute(
            "SELECT password_hash FROM platform_users WHERE username = ?",
            (USERNAME,),
        ).fetchone()
        connection.close()
        return None if row is None else row[0]

    def run_script(self) -> str:
        module = load_script()
        with patch.dict("sys.modules", credentials_module()):
            return module.realign(self.db_path, USERNAME, PASSWORD)

    def test_a_rotated_password_reaches_the_seeded_administrator(self) -> None:
        self.seed(PREVIOUS)
        self.assertEqual(
            self.run_script(),
            "CHANGED",
            "SH_ADMIN_PASSWORD seeds the administrator on first boot only, so a "
            "rotated credential reaches an existing household through this "
            "realign or not at all",
        )
        self.assertEqual(self.stored_hash(), f"scrypt$fake${PASSWORD}")

    def test_an_aligned_password_is_left_alone(self) -> None:
        self.seed(PASSWORD)
        self.assertEqual(self.run_script(), "UNCHANGED")
        self.assertEqual(self.stored_hash(), f"scrypt$fake${PASSWORD}")

    def test_a_missing_administrator_row_fails_loudly(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.run_script()
        self.assertIn("[FAIL]", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
