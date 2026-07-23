import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from . import PROJECT_ROOT

SCRIPT_REL = Path("scripts/meta/resolve/diff/affected_roles.sh")
SCRIPT_PATH = PROJECT_ROOT / SCRIPT_REL

ROLE_TASKS_MAIN_REL = f"roles/web-app-foo/{ROLE_FILE_TASKS_MAIN}"


@unittest.skipUnless(shutil.which("git"), "git is required for this test")
class TestDiffAffectedRoles(unittest.TestCase):
    def _setup_repo(
        self,
        *,
        base_files: dict[str, str],
        feature_files: dict[str, str],
        fake_resolver_stdout: str = "",
    ) -> tuple[Path, dict[str, str]]:
        tmp = Path(tempfile.mkdtemp(prefix="affected-roles-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        repo = tmp / "work"
        bare = tmp / "remote.git"

        subprocess.run(
            ["git", "init", "--bare", "-q", "-b", "main", str(bare)],
            check=True,
        )

        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "ci@example.com"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "config", "user.name", "ci"], cwd=repo, check=True)
        # Exception: hermetic fixture — an operator's global commit.gpgsign=true
        # would make these scratch commits launch pinentry and fail off-terminal.
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True
        )
        subprocess.run(
            ["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True
        )

        # Exception: the real script MUST land at its expected relative path —
        # its SCRIPT_DIR/REPO_ROOT computation must resolve inside the temp repo.
        script_target = repo / SCRIPT_REL
        script_target.parent.mkdir(parents=True)
        shutil.copy2(SCRIPT_PATH, script_target)
        script_target.chmod(0o755)

        for rel, content in base_files.items():
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
        subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True)

        subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
        for rel, content in feature_files.items():
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "feature"], cwd=repo, check=True)

        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        fake_python = bin_dir / "python-fake-resolver"
        fake_python.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                printf '%s\\n' {shlex.quote(fake_resolver_stdout)}
                """
            ),
            encoding="utf-8",
        )
        fake_python.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["INFINITO_DISTRO"] = "test"
        env["PYTHON"] = str(fake_python)
        env.pop("BASH_ENV", None)

        return repo, env

    def _run_script(self, repo: Path, env: dict[str, str]) -> str:
        script = repo / SCRIPT_REL
        result = subprocess.run(
            ["bash", str(script)],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def test_md_outside_role_is_skipped_when_role_also_changed(self):
        repo, env = self._setup_repo(
            base_files={
                ROLE_TASKS_MAIN_REL: "- debug: msg=v1\n",
                "README.md": "v1\n",
            },
            feature_files={
                ROLE_TASKS_MAIN_REL: "- debug: msg=v2\n",
                "README.md": "v2\n",
                "docs/contributing/x.md": "doc\n",
            },
            fake_resolver_stdout="web-app-foo",
        )
        self.assertEqual(self._run_script(repo, env), "web-app-foo")

    def test_rst_outside_role_is_skipped_when_role_also_changed(self):
        repo, env = self._setup_repo(
            base_files={ROLE_TASKS_MAIN_REL: "- debug: msg=v1\n"},
            feature_files={
                ROLE_TASKS_MAIN_REL: "- debug: msg=v2\n",
                "docs/foo.rst": "doc\n",
            },
            fake_resolver_stdout="web-app-foo",
        )
        self.assertEqual(self._run_script(repo, env), "web-app-foo")

    def test_non_md_outside_role_still_triggers_all(self):
        repo, env = self._setup_repo(
            base_files={ROLE_TASKS_MAIN_REL: "- debug: msg=v1\n"},
            feature_files={
                ROLE_TASKS_MAIN_REL: "- debug: msg=v2\n",
                "Makefile": "all:\n\t@true\n",
            },
        )
        self.assertEqual(self._run_script(repo, env), "__ALL__")

    def test_only_md_outside_role_falls_back_to_all(self):
        repo, env = self._setup_repo(
            base_files={"README.md": "v1\n"},
            feature_files={
                "README.md": "v2\n",
                "docs/x.md": "new\n",
            },
        )
        self.assertEqual(self._run_script(repo, env), "__ALL__")

    def test_only_role_changes_pass_through_resolver(self):
        repo, env = self._setup_repo(
            base_files={ROLE_TASKS_MAIN_REL: "- debug: msg=v1\n"},
            feature_files={
                ROLE_TASKS_MAIN_REL: "- debug: msg=v2\n",
            },
            fake_resolver_stdout="web-app-foo",
        )
        self.assertEqual(self._run_script(repo, env), "web-app-foo")


if __name__ == "__main__":
    unittest.main()
