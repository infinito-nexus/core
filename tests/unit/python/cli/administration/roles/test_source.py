from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli.administration.roles import source as source_module
from cli.administration.roles.declaration import Source
from cli.administration.roles.source import check, stage
from utils.cache.files import read_text
from utils.roles.custom import CustomRoleError
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from ._fixtures import ROLE, ROLE_PATH, git, role_repo, roles_dir, write


class _SourceFixture:
    """Mixin with a core roles/ and a role repository.

    Combined with ``unittest.TestCase`` on each concrete class so the
    test-discovery lint sees the ``TestCase`` base directly.
    """

    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.roles = roles_dir(self.root)
        self.repo = role_repo(self.root)

    def check(self, source: Source, placements: tuple[Path, ...] = ()) -> None:
        check(ROLE, source, list(placements), self.roles)


class TestCheckVersion(_SourceFixture, unittest.TestCase):
    def test_tag_is_accepted(self):
        self.check(Source(str(self.repo), "v1.0.0", ROLE_PATH))

    def test_full_commit_sha_is_accepted(self):
        sha = git(self.repo, "rev-parse", "v1.0.0").strip()
        self.check(Source(str(self.repo), sha, ROLE_PATH))

    def test_full_commit_sha_needs_no_ref_lookup(self):
        self.check(Source("https://example.invalid/widgets.git", "a" * 40, ROLE_PATH))

    def test_branch_is_refused(self):
        with self.assertRaisesRegex(
            CustomRoleError, f"{ROLE}: source.version 'feature' names a branch"
        ):
            self.check(Source(str(self.repo), "feature", ROLE_PATH))

    def test_abbreviated_sha_is_refused(self):
        sha = git(self.repo, "rev-parse", "--short", "v1.0.0").strip()
        with self.assertRaisesRegex(
            CustomRoleError, "neither a tag nor a full commit SHA"
        ):
            self.check(Source(str(self.repo), sha, ROLE_PATH))

    def test_unknown_tag_is_refused(self):
        with self.assertRaisesRegex(CustomRoleError, "'v9.9.9' is neither a tag"):
            self.check(Source(str(self.repo), "v9.9.9", ROLE_PATH))


class TestCheckLocalSource(_SourceFixture, unittest.TestCase):
    def test_missing_directory_is_refused(self):
        with self.assertRaisesRegex(CustomRoleError, "is not a directory"):
            self.check(Source(str(self.root / "absent"), None, ROLE_PATH))

    def test_own_placement_directory_is_refused_naming_the_path(self):
        (self.roles / ROLE).mkdir()
        placement = re.escape(str((self.roles / ROLE).resolve()))
        with self.assertRaisesRegex(
            CustomRoleError, f"{placement} lies in the placement directory"
        ):
            self.check(Source(str(self.root), None, f"roles/{ROLE}"))

    def test_another_placement_is_refused(self):
        other = self.roles / "web-app-cst-other"
        other.mkdir()
        with self.assertRaisesRegex(CustomRoleError, "never deletes its own source"):
            self.check(
                Source(str(self.root), None, f"roles/{other.name}/{ROLE}"), (other,)
            )

    def test_placement_reached_through_a_symlink_is_refused(self):
        (self.roles / ROLE).symlink_to(self.repo / ROLE_PATH)
        with self.assertRaisesRegex(CustomRoleError, "never deletes its own source"):
            self.check(Source(str(self.repo), None, ROLE_PATH))

    def test_source_through_a_symlinked_checkout_is_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root)
        with self.assertRaisesRegex(CustomRoleError, "never deletes its own source"):
            self.check(Source(str(alias), None, f"roles/{ROLE}"))

    def test_checkout_outside_roles_is_accepted(self):
        self.check(Source(str(self.repo), None, ROLE_PATH))


class TestStage(_SourceFixture, unittest.TestCase):
    def test_tag_stages_only_the_role_path_at_that_tag(self):
        target = self.root / "staged"
        origin = stage(ROLE, Source(str(self.repo), "v1.0.0", ROLE_PATH), target)
        sha = git(self.repo, "rev-parse", "v1.0.0^{commit}").strip()
        self.assertEqual("release: v1\n", read_text(str(target / ROLE_FILE_TASKS_MAIN)))
        self.assertFalse((target / "README.md").exists())
        self.assertIn(f"(commit {sha})", origin)

    def test_full_commit_sha_is_staged(self):
        sha = git(self.repo, "rev-parse", "v1.0.0^{commit}").strip()
        target = self.root / "staged"
        stage(ROLE, Source(str(self.repo), sha, ROLE_PATH), target)
        self.assertEqual("release: v1\n", read_text(str(target / ROLE_FILE_TASKS_MAIN)))

    def test_local_directory_without_version_is_its_working_tree(self):
        write(self.repo / ROLE_PATH / ROLE_FILE_TASKS_MAIN, "release: uncommitted\n")
        (self.repo / ROLE_PATH / "__pycache__").mkdir()
        target = self.root / "staged"
        origin = stage(ROLE, Source(str(self.repo), None, ROLE_PATH), target)
        self.assertEqual(
            "release: uncommitted\n", read_text(str(target / ROLE_FILE_TASKS_MAIN))
        )
        self.assertFalse((target / "__pycache__").exists())
        self.assertIn("(working tree)", origin)

    def test_local_directory_skips_unreadable_agent_harness_state(self):
        harness = self.repo / ROLE_PATH / ".claude" / ".cc-writes"
        harness.mkdir(parents=True)
        harness.chmod(0o000)
        self.addCleanup(harness.chmod, 0o700)
        target = self.root / "staged"
        stage(ROLE, Source(str(self.repo), None, ROLE_PATH), target)
        self.assertFalse((target / ".claude").exists())

    def test_path_that_is_a_file_is_refused(self):
        with self.assertRaisesRegex(CustomRoleError, "source.path is not a directory"):
            stage(ROLE, Source(str(self.repo), "v1.0.0", "README.md"), self.root / "s")

    def test_missing_path_is_refused(self):
        with self.assertRaisesRegex(CustomRoleError, "source.path is not a directory"):
            stage(
                ROLE,
                Source(str(self.repo), "v1.0.0", f"absent/{ROLE}"),
                self.root / "s",
            )

    def test_failed_fetch_names_the_group(self):
        with self.assertRaisesRegex(
            CustomRoleError, f"{ROLE}: git fetch of v1.0.0 failed"
        ):
            stage(
                ROLE,
                Source(str(self.root / "absent"), "v1.0.0", ROLE_PATH),
                self.root / "staged",
            )


class TestGitNeverPrompts(unittest.TestCase):
    def test_git_runs_detached_without_a_prompt_or_askpass(self):
        failed = subprocess.CompletedProcess(
            ["git"], 128, stdout=b"", stderr=b"fatal: could not read Username"
        )
        source = Source("git@example.invalid:acme/widgets.git", "v1.0.0", ROLE_PATH)
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(
                "os.environ",
                {
                    "GIT_ASKPASS": "/bin/askpass",
                    "SSH_ASKPASS": "/bin/askpass",
                    "SSH_AUTH_SOCK": "/run/agent.sock",
                },
            ),
            mock.patch.object(
                source_module.subprocess, "run", return_value=failed
            ) as run,
            self.assertRaisesRegex(CustomRoleError, "could not read Username"),
        ):
            stage(ROLE, source, Path(tmp) / "staged")
        kwargs = run.call_args.kwargs
        self.assertEqual("0", kwargs["env"]["GIT_TERMINAL_PROMPT"])
        self.assertEqual("never", kwargs["env"]["SSH_ASKPASS_REQUIRE"])
        self.assertNotIn("GIT_ASKPASS", kwargs["env"])
        self.assertNotIn("SSH_ASKPASS", kwargs["env"])
        self.assertEqual("/run/agent.sock", kwargs["env"]["SSH_AUTH_SOCK"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(subprocess.DEVNULL, kwargs["stdin"])


if __name__ == "__main__":
    unittest.main()
