from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cli.administration.roles.placement import clean, pull
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = "web-app-cst-demo"
_ENV = {
    **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
}


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=ci",
            "-c",
            "user.email=ci@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *arguments,
        ],
        cwd=repository,
        env=_ENV,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@unittest.skipUnless(shutil.which("git"), "git is required for this test")
class TestPulledRoleStaysOutOfGit(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.checkout = base / "core"
        self.roles = self.checkout / "roles"
        self.work = self.checkout / "build" / "custom-roles"
        _write(
            self.checkout / ".gitignore", read_text(str(PROJECT_ROOT / ".gitignore"))
        )
        _write(
            self.roles / "web-app-nextcloud" / ROLE_FILE_META_MAIN, "galaxy_info: {}\n"
        )
        _git(self.checkout, "init", "--quiet")
        _git(self.checkout, "add", "--all")
        _git(self.checkout, "commit", "--quiet", "--no-verify", "--message", "core")
        source = base / "landingpage" / "ansible" / "roles" / ROLE
        _write(source / ROLE_FILE_META_MAIN, "galaxy_info: {}\n")
        _write(source / ROLE_FILE_VARS_MAIN, f"application_id: {ROLE}\n")
        applications = {
            ROLE: {
                "custom": True,
                "source": {
                    "url": str(base / "landingpage"),
                    "path": f"ansible/roles/{ROLE}",
                },
            }
        }
        _write(
            base / "inventory" / "host_vars" / "localhost.yml",
            json.dumps({"applications": applications}),
        )
        _write(
            base / "inventory" / "devices.yml",
            json.dumps({"all": {"children": {ROLE: {"hosts": {"localhost": {}}}}}}),
        )
        self.inventory = base / "inventory" / "devices.yml"

    def test_a_pulled_role_leaves_git_status_empty(self) -> None:
        pull(self.inventory, self.roles, self.work)
        self.assertTrue((self.roles / ROLE / ROLE_FILE_VARS_MAIN).is_file())
        self.assertEqual("", _git(self.checkout, "status", "--porcelain"))
        self.assertIn(
            f"roles/{ROLE}/",
            _git(self.checkout, "status", "--porcelain", "--ignored"),
        )

    def test_clean_leaves_only_the_tracked_roles(self) -> None:
        pull(self.inventory, self.roles, self.work)
        clean(self.roles, self.work)
        self.assertEqual(["web-app-nextcloud"], [e.name for e in self.roles.iterdir()])
        self.assertEqual(
            "", _git(self.checkout, "status", "--porcelain", "--ignored", "roles")
        )


if __name__ == "__main__":
    unittest.main()
