from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

SCRIPT = (
    PROJECT_ROOT / "scripts" / "github" / "resolve" / "pr" / "role_skeleton_affected.sh"
)
ROLE_TASKS = f"roles/web-app-nextcloud/{ROLE_FILE_TASKS_MAIN}"
BASE = {
    "templates/roles/skeleton/meta/main.yml.tmpl": "v1\n",
    "cli/contributing/role/skeleton/render.py": "v1\n",
    "tests/lint/ansible/roles/test_x.py": "v1\n",
    "tests/integration/roles/test_y.py": "v1\n",
    "utils/roles/mapping.py": "v1\n",
    ROLE_TASKS: "v1\n",
    "README.md": "v1\n",
}


class TestRoleSkeletonAffected(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        self.output = Path(tmp.name) / "github_output"
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        self.repo.mkdir()
        self._git("init", "-q", "-b", "main")
        self._commit(BASE)
        self.base = self._git("rev-parse", "HEAD").strip()

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def _commit(self, files: dict[str, str]) -> None:
        for rel, text in files.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "change")

    def _affected(self, changed: str) -> str:
        self._commit({changed: "v2\n"})
        script = self.repo.parent / "role_skeleton_affected.sh"
        shutil.copy2(SCRIPT, script)
        subprocess.run(
            ["bash", str(script)],
            cwd=self.repo,
            env={**self.env, "BASE_SHA": self.base, "GITHUB_OUTPUT": str(self.output)},
            capture_output=True,
            text=True,
            check=True,
        )
        return read_text(str(self.output))

    def test_a_skeleton_template_is_affected(self):
        self.assertEqual(
            "affected=true\n",
            self._affected("templates/roles/skeleton/meta/main.yml.tmpl"),
        )

    def test_the_renderer_is_affected(self):
        self.assertEqual(
            "affected=true\n",
            self._affected("cli/contributing/role/skeleton/render.py"),
        )

    def test_a_role_lint_is_affected(self):
        self.assertEqual(
            "affected=true\n", self._affected("tests/lint/ansible/roles/test_x.py")
        )

    def test_a_role_integration_test_is_affected(self):
        self.assertEqual(
            "affected=true\n", self._affected("tests/integration/roles/test_y.py")
        )

    def test_the_role_mapping_is_affected(self):
        self.assertEqual("affected=true\n", self._affected("utils/roles/mapping.py"))

    def test_a_role_change_is_not(self):
        self.assertEqual("affected=false\n", self._affected(ROLE_TASKS))

    def test_a_change_elsewhere_is_not(self):
        self.assertEqual("affected=false\n", self._affected("README.md"))


if __name__ == "__main__":
    unittest.main()
