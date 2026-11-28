"""Contract of ``scripts/github/resolve/pr/agents_affected.sh``.

The agents CI lane runs on a pull request that touches ``agents/`` or an AI
role. A role is an AI role when its ``meta/main.yml`` carries the galaxy tag
``ai``, so a runtime such as ``web-app-hermes`` triggers the lane without a
hardcoded role list, and a role without the tag does not.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_TASKS_MAIN

SCRIPT = PROJECT_ROOT / "scripts" / "github" / "resolve" / "pr" / "agents_affected.sh"
META = "galaxy_info:\n  galaxy_tags:\n    - {tag}\n    - self-hosted\n"
BASE = {
    f"roles/web-app-hermes/{ROLE_FILE_META_MAIN}": META.format(tag="ai"),
    f"roles/web-app-hermes/{ROLE_FILE_TASKS_MAIN}": "- debug: msg=v1\n",
    f"roles/web-app-nextcloud/{ROLE_FILE_META_MAIN}": META.format(tag="cloud"),
    f"roles/web-app-nextcloud/{ROLE_FILE_TASKS_MAIN}": "- debug: msg=v1\n",
    "README.md": "v1\n",
}


class TestAgentsAffected(unittest.TestCase):
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

    def _affected(self, files: dict[str, str]) -> str:
        self._commit(files)
        script = self.repo / "scripts" / "agents_affected.sh"
        script.parent.mkdir(exist_ok=True)
        shutil.copy2(SCRIPT, script)
        subprocess.run(
            ["bash", str(script)],
            cwd=self.repo,
            env={
                **self.env,
                "BASE_SHA": self.base,
                "GITHUB_OUTPUT": str(self.output),
            },
            capture_output=True,
            text=True,
            check=True,
        )
        return read_text(str(self.output))

    def test_a_role_tagged_ai_is_affected(self):
        changed = {f"roles/web-app-hermes/{ROLE_FILE_TASKS_MAIN}": "- debug: msg=v2\n"}
        self.assertEqual(self._affected(changed), "affected=true\n")

    def test_a_role_without_the_ai_tag_is_not(self):
        changed = {
            f"roles/web-app-nextcloud/{ROLE_FILE_TASKS_MAIN}": "- debug: msg=v2\n"
        }
        self.assertEqual(self._affected(changed), "affected=false\n")

    def test_the_agents_tree_is_affected(self):
        self.assertEqual(self._affected({"agents/x.yml": "x: 1\n"}), "affected=true\n")

    def test_a_change_outside_roles_and_agents_is_not(self):
        self.assertEqual(self._affected({"README.md": "v2\n"}), "affected=false\n")


if __name__ == "__main__":
    unittest.main()
