from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "install" / "skills.sh"

SKILLS_MAKEFILE = (
    "project:\n"
    '\t@printf \'%s\\n\' "$(TARGET)" >>"$(SKILLS_TEST_LOG)"\n'
    "\t@for d in .agents/skills .claude/skills; do "
    'rm -rf "$(TARGET)/$$d"; '
    'mkdir -p "$(TARGET)/$$d/upstream" "$(TARGET)/$$d/i8-demo"; '
    'cp VERSION "$(TARGET)/$$d/upstream/VERSION"; '
    'printf upstream >"$(TARGET)/$$d/i8-demo/SKILL.md"; '
    "done\n"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")  # nocheck: cache-read


def _git(cwd: Path, env: dict[str, str], *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit(repo: Path, env: dict[str, str], files: dict[str, str]) -> str:
    for name, body in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _git(repo, env, "add", "-A")
    _git(repo, env, "commit", "--quiet", "--no-verify", "-m", "fixture")
    return _git(repo, env, "rev-parse", "HEAD")


def _isolated_env(root: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "MAKE", "INFINITO_"))
        and key not in {"BASH_ENV", "ENV_SH", "MFLAGS"}
    }
    gitconfig = root / "gitconfig"
    gitconfig.write_text("", encoding="utf-8")
    env.update(
        GIT_CONFIG_GLOBAL=str(gitconfig),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="test",
        GIT_AUTHOR_EMAIL="test@example.invalid",
        GIT_COMMITTER_NAME="test",
        GIT_COMMITTER_EMAIL="test@example.invalid",
    )
    return env


class _InstallCase:
    @classmethod
    def setUpClass(cls) -> None:
        cls._skills_tmp = tempfile.TemporaryDirectory()
        root = Path(cls._skills_tmp.name).resolve()
        cls.base_env = _isolated_env(root)
        cls.skills = root / "skills"
        cls.skills.mkdir()
        _git(cls.skills, cls.base_env, "init", "--quiet", "-b", "master")
        cls.v1 = _commit(
            cls.skills, cls.base_env, {"Makefile": SKILLS_MAKEFILE, "VERSION": "v1"}
        )
        cls.v2 = _commit(cls.skills, cls.base_env, {"VERSION": "v2"})
        _git(cls.skills, cls.base_env, "checkout", "--quiet", "-b", "feature")
        _commit(cls.skills, cls.base_env, {"VERSION": "v3"})
        _git(cls.skills, cls.base_env, "checkout", "--quiet", "master")
        (cls.skills / "VERSION").write_text("uncommitted", encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._skills_tmp.cleanup()

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.log = root / "installs.log"
        self.env = dict(self.base_env, SKILLS_TEST_LOG=str(self.log))
        self.main = root / "main"
        self.main.mkdir()
        _git(self.main, self.env, "init", "--quiet", "-b", "main")
        script = self.main / "scripts" / "install" / "skills.sh"
        script.parent.mkdir(parents=True)
        shutil.copy2(SCRIPT, script)
        _commit(
            self.main,
            self.env,
            {
                "AGENTS.md": "main agents",
                "agents/skills/i8-demo/SKILL.md": "main branch",
            },
        )
        self.worktree = root / "worktree"
        _git(
            self.main,
            self.env,
            "worktree",
            "add",
            "--quiet",
            "-b",
            "feature-branch",
            str(self.worktree),
        )
        (self.worktree / "AGENTS.md").write_text("worktree agents", encoding="utf-8")
        (self.worktree / "agents/skills/i8-demo/SKILL.md").write_text(
            "worktree branch", encoding="utf-8"
        )

    def _install(
        self, checkout: Path, targets: str, ref: str = "master"
    ) -> subprocess.CompletedProcess[str]:
        env = dict(
            self.env,
            INFINITO_SKILLS_REPOSITORY=str(self.skills),
            INFINITO_SKILLS_REF=ref,
            INFINITO_SKILLS_TARGETS=targets,
        )
        return subprocess.run(
            ["bash", str(checkout / "scripts" / "install" / "skills.sh")],
            cwd=checkout,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _installed(self) -> list[str]:
        if not self.log.exists():
            return []
        return _read(self.log).splitlines()

    def _assert_ok(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)

    def _version(self, checkout: Path) -> str:
        return _read(checkout / ".agents" / "skills" / "upstream" / "VERSION")


class TestTargetResolution(_InstallCase, unittest.TestCase):
    def test_worktree_installs_into_the_running_checkout_only(self) -> None:
        self._assert_ok(self._install(self.worktree, "worktree"))

        self.assertEqual(self._installed(), [str(self.worktree)])
        self.assertFalse((self.main / ".agents").exists())

    def test_main_is_the_first_entry_of_the_worktree_list(self) -> None:
        self._assert_ok(self._install(self.worktree, "main"))

        self.assertEqual(self._installed(), [str(self.main)])
        self.assertFalse((self.worktree / ".agents").exists())

    def test_worktree_and_main_install_into_both_in_order(self) -> None:
        self._assert_ok(self._install(self.worktree, "worktree main"))

        self.assertEqual(self._installed(), [str(self.worktree), str(self.main)])

    def test_a_duplicate_target_installs_once(self) -> None:
        self._assert_ok(self._install(self.worktree, "worktree main worktree main"))

        self.assertEqual(self._installed(), [str(self.worktree), str(self.main)])

    def test_worktree_and_main_collapse_in_the_primary_checkout(self) -> None:
        self._assert_ok(self._install(self.main, "worktree main"))

        self.assertEqual(self._installed(), [str(self.main)])

    def test_an_unknown_target_fails_naming_it_before_installing(self) -> None:
        result = self._install(self.worktree, "worktree bogus")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("'bogus'", result.stderr)
        self.assertEqual(self._installed(), [])

    def test_a_blank_target_list_fails(self) -> None:
        result = self._install(self.worktree, " ")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._installed(), [])


class TestLayering(_InstallCase, unittest.TestCase):
    def test_main_receives_the_running_checkouts_skills_on_top(self) -> None:
        self._assert_ok(self._install(self.worktree, "worktree main"))

        for skills in (".agents/skills", ".claude/skills"):
            with self.subTest(skills=skills):
                self.assertEqual(
                    _read(self.main / skills / "i8-demo" / "SKILL.md"),
                    "worktree branch",
                )
                self.assertEqual(
                    _read(self.main / skills / "upstream" / "VERSION"), "v2"
                )

    def test_agents_md_stays_per_branch(self) -> None:
        self._assert_ok(self._install(self.worktree, "worktree main"))

        self.assertEqual(_read(self.main / "AGENTS.md"), "main agents")


class TestSkillsRef(_InstallCase, unittest.TestCase):
    def test_a_commit_sha_installs_that_commit(self) -> None:
        self._assert_ok(self._install(self.worktree, "worktree", ref=self.v1))

        self.assertEqual(self._version(self.worktree), "v1")

    def test_an_abbreviated_sha_installs_that_commit(self) -> None:
        self._assert_ok(self._install(self.worktree, "worktree", ref=self.v1[:10]))

        self.assertEqual(self._version(self.worktree), "v1")

    def test_a_branch_installs_its_head(self) -> None:
        self._assert_ok(self._install(self.worktree, "worktree", ref="feature"))

        self.assertEqual(self._version(self.worktree), "v3")

    def test_a_local_path_installs_the_committed_state(self) -> None:
        self._assert_ok(self._install(self.worktree, "worktree", ref="master"))

        self.assertEqual(self._version(self.worktree), "v2")

    def test_an_unknown_ref_fails_before_installing(self) -> None:
        result = self._install(self.worktree, "worktree", ref="no-such-ref")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._installed(), [])


if __name__ == "__main__":
    unittest.main()
