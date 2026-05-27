# Unit tests for roles/sys-util-git-pull/files/sys_util_git_pull.py
#
# Option A: import the script via file path (because role paths contain dashes)
#
# Run:
#   python -m unittest -v tests.unit.roles.sys-util-git-pull.files.test_sys_util_git_pull
#
from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from . import PROJECT_ROOT


def _load_sut():
    """
    Load roles/sys-util-git-pull/files/sys_util_git_pull.py as module "sys_util_git_pull"
    so unittest.mock.patch can reference it via "sys_util_git_pull.<name>".
    """
    script_path = (
        PROJECT_ROOT / "roles" / "sys-util-git-pull" / "files" / "sys_util_git_pull.py"
    )

    if not script_path.exists():
        raise FileNotFoundError(f"sys_util_git_pull.py not found at: {script_path}")

    spec = importlib.util.spec_from_file_location("sys_util_git_pull", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for: {script_path}")

    module = importlib.util.module_from_spec(spec)
    # Register so patch("sys_util_git_pull.<...>") works.
    sys.modules["sys_util_git_pull"] = module
    spec.loader.exec_module(module)
    return module


# Load once at import time
sut = _load_sut()


class SysUtilGitPullTests(unittest.TestCase):
    def test_log_writes_to_stderr_when_verbose(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            sut.log("hello", verbose=True)
        self.assertIn("[git-pull] hello", buf.getvalue())

    def test_log_is_silent_when_not_verbose(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            sut.log("hello", verbose=False)
        self.assertEqual("", buf.getvalue())

    @patch("sys_util_git_pull.subprocess.run")
    def test_run_returns_stripped_output(self, m_run: MagicMock) -> None:
        m_run.return_value = MagicMock(
            returncode=0, stdout="  ok \n", stderr="  err \n"
        )
        res = sut.run(["echo", "x"], cwd="/tmp", verbose=False)
        self.assertEqual(0, res.rc)
        self.assertEqual("ok", res.stdout)
        self.assertEqual("err", res.stderr)

    def test_run_checked_raises_on_non_transient_failure(self) -> None:
        # Non-transient: stderr doesn't match any transient markers
        with patch.object(
            sut, "run", return_value=sut.RunResult(2, "out", "some permanent error")
        ):
            with self.assertRaises(RuntimeError) as ctx:
                sut.run_checked(["false"], cwd="/tmp", verbose=False, retries=3)
            self.assertIn("Command failed (rc=2)", str(ctx.exception))

    def test_run_checked_retries_on_transient_then_succeeds(self) -> None:
        # Transient: contains e.g. "Connection reset by peer"
        seq = [
            sut.RunResult(128, "", "fatal: ... Recv failure: Connection reset by peer"),
            sut.RunResult(0, "ok", ""),
        ]
        with (
            patch.object(sut, "run", side_effect=seq) as m_run,
            patch("sys_util_git_pull.time.sleep") as m_sleep,
        ):
            r = sut.run_checked(
                ["git", "clone", "x"], cwd=None, verbose=True, retries=5
            )
            self.assertEqual(0, r.rc)
            self.assertEqual("ok", r.stdout)
            self.assertEqual(2, m_run.call_count)
            m_sleep.assert_called()  # backoff happened at least once

    @patch("sys_util_git_pull.os.listdir")
    def test_is_dir_empty_true_for_missing_dir(self, m_listdir: MagicMock) -> None:
        m_listdir.side_effect = FileNotFoundError()
        self.assertTrue(sut.is_dir_empty("/does/not/exist"))

    @patch("sys_util_git_pull.os.listdir")
    def test_is_dir_empty_true_for_empty(self, m_listdir: MagicMock) -> None:
        m_listdir.return_value = []
        self.assertTrue(sut.is_dir_empty("/tmp/x"))

    @patch("sys_util_git_pull.os.listdir")
    def test_is_dir_empty_false_for_non_empty(self, m_listdir: MagicMock) -> None:
        m_listdir.return_value = ["file"]
        self.assertFalse(sut.is_dir_empty("/tmp/x"))

    def test_remote_exists_true_when_remote_list_contains_name(self) -> None:
        # remote_exists now uses run(["git","remote"]) directly
        with patch.object(
            sut, "run", return_value=sut.RunResult(0, "origin\nupstream\n", "")
        ):
            self.assertTrue(sut.remote_exists("/repo", "origin", verbose=False))
            self.assertTrue(sut.remote_exists("/repo", "upstream", verbose=False))
            self.assertFalse(sut.remote_exists("/repo", "nope", verbose=False))

    def test_remote_exists_raises_when_git_remote_fails(self) -> None:
        with patch.object(
            sut, "run", return_value=sut.RunResult(1, "", "fatal: not a git repository")
        ):
            with self.assertRaises(RuntimeError) as ctx:
                sut.remote_exists("/repo", "origin", verbose=False)
            self.assertIn("Command failed (rc=1): git remote", str(ctx.exception))

    def test_tag_exists_uses_rev_parse_rc(self) -> None:
        # tag_exists now uses run([...rev-parse...]) directly
        with patch.object(sut, "run", return_value=sut.RunResult(0, "", "")):
            self.assertTrue(sut.tag_exists("/repo", "stable", verbose=False))
        with patch.object(sut, "run", return_value=sut.RunResult(1, "", "")):
            self.assertFalse(sut.tag_exists("/repo", "stable", verbose=False))

    def test_delete_tag_if_exists_deletes_and_returns_true(self) -> None:
        with (
            patch.object(sut, "tag_exists", return_value=True),
            patch.object(sut, "git") as m_git,
        ):
            self.assertTrue(sut.delete_tag_if_exists("/repo", "stable", verbose=True))
            m_git.assert_called_with("/repo", True, "tag", "-d", "stable", retries=3)

    def test_delete_tag_if_exists_returns_false_when_missing(self) -> None:
        with (
            patch.object(sut, "tag_exists", return_value=False),
            patch.object(sut, "git") as m_git,
        ):
            self.assertFalse(sut.delete_tag_if_exists("/repo", "stable", verbose=False))
            m_git.assert_not_called()

    def test_get_local_tag_commit_returns_commit_on_rc0(self) -> None:
        # get_local_tag_commit uses run([...rev-parse...]) directly
        with patch.object(sut, "run", return_value=sut.RunResult(0, "abc123\n", "")):
            self.assertEqual(
                "abc123", sut.get_local_tag_commit("/repo", "stable", verbose=False)
            )
        with patch.object(sut, "run", return_value=sut.RunResult(1, "abc123\n", "")):
            self.assertEqual(
                "", sut.get_local_tag_commit("/repo", "stable", verbose=False)
            )

    def test_resolve_remote_tag_commit_prefers_peeled(self) -> None:
        def fake_run_checked(
            cmd, cwd, verbose, retries=5, backoff_cap_seconds=20
        ) -> sut.RunResult:
            # cmd: ["git","ls-remote","--tags",remote,"stable^{}"] or fallback "stable"
            if cmd[-1].endswith("^{}"):
                return sut.RunResult(0, "deadbeef\trefs/tags/stable^{}\n", "")
            return sut.RunResult(0, "cafebabe\trefs/tags/stable\n", "")

        with patch.object(sut, "run_checked", side_effect=fake_run_checked):
            self.assertEqual(
                "deadbeef",
                sut.resolve_remote_tag_commit(
                    "/repo", "origin", "stable", verbose=False
                ),
            )

    def test_resolve_remote_tag_commit_falls_back_to_lightweight(self) -> None:
        def fake_run_checked(
            cmd, cwd, verbose, retries=5, backoff_cap_seconds=20
        ) -> sut.RunResult:
            if cmd[-1].endswith("^{}"):
                return sut.RunResult(0, "", "")
            return sut.RunResult(0, "cafebabe\trefs/tags/stable\n", "")

        with patch.object(sut, "run_checked", side_effect=fake_run_checked):
            self.assertEqual(
                "cafebabe",
                sut.resolve_remote_tag_commit(
                    "/repo", "origin", "stable", verbose=False
                ),
            )

    def test_resolve_remote_tag_commit_returns_empty_when_missing(self) -> None:
        with patch.object(sut, "run_checked", return_value=sut.RunResult(0, "", "")):
            self.assertEqual(
                "",
                sut.resolve_remote_tag_commit(
                    "/repo", "origin", "stable", verbose=False
                ),
            )

    def test_main_clone_new_repo_and_pin_tag_sets_changed_true(self) -> None:
        """
        Scenario:
          - dest is not a git repo
          - dest is empty
          - clone happens
          - pin-tag happens, local_before empty => changed true
        """
        argv = [
            "prog",
            "--repo-url",
            "https://example.com/repo.git",
            "--dest",
            "/dest",
            "--branch",
            "main",
            "--depth",
            "1",
            "--remote",
            "origin",
            "--pin-tag",
            "stable",
        ]

        with (
            patch.object(sut, "ensure_dir") as m_ensure,
            patch.object(sut, "is_git_repo", return_value=False),
            patch.object(sut, "is_dir_empty", return_value=True),
            patch.object(sut, "clone_shallow") as m_clone,
            patch.object(sut, "get_local_tag_commit", return_value=""),
            patch.object(sut, "resolve_remote_tag_commit", return_value=""),
            patch.object(sut, "fetch_tag_shallow") as m_fetch_tag,
            patch.object(sut, "checkout_detached") as m_detach,
            patch("sys_util_git_pull.sys.argv", argv),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = sut.main()
            self.assertEqual(0, rc)
            self.assertIn("CHANGED=true", out.getvalue())
            self.assertIn("PIN_TAG=stable", out.getvalue())
            m_ensure.assert_called()
            m_clone.assert_called_once()
            m_fetch_tag.assert_called_once()
            m_detach.assert_called_once()

    def test_main_existing_repo_remote_missing_raises(self) -> None:
        argv = [
            "prog",
            "--repo-url",
            "https://example.com/repo.git",
            "--dest",
            "/dest",
        ]
        with (
            patch.object(sut, "ensure_dir"),
            patch.object(sut, "is_git_repo", return_value=True),
            patch.object(sut, "remote_exists", return_value=False),
            patch("sys_util_git_pull.sys.argv", argv),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                sut.main()
            self.assertIn("Remote 'origin' not configured", str(ctx.exception))

    def test_main_existing_repo_deletes_tags_and_updates_branch(self) -> None:
        argv = [
            "prog",
            "--repo-url",
            "https://example.com/repo.git",
            "--dest",
            "/dest",
            "--remove-tag",
            "latest",
            "--remove-tag",
            "stable",
        ]
        with (
            patch.object(sut, "ensure_dir"),
            patch.object(sut, "is_git_repo", return_value=True),
            patch.object(sut, "remote_exists", return_value=True),
            patch.object(
                sut, "delete_tag_if_exists", side_effect=[True, False]
            ) as m_del,
            patch.object(sut, "fetch_branch_shallow") as m_fetch_branch,
            patch("sys_util_git_pull.sys.argv", argv),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = sut.main()
            self.assertEqual(0, rc)
            self.assertIn("CHANGED=true", out.getvalue())
            m_del.assert_any_call("/dest", "latest", False)
            m_del.assert_any_call("/dest", "stable", False)
            m_fetch_branch.assert_called_once_with("/dest", "origin", "main", 1, False)

    def test_main_tag_moved_sets_changed_true_when_flag_enabled(self) -> None:
        argv = [
            "prog",
            "--repo-url",
            "https://example.com/repo.git",
            "--dest",
            "/dest",
            "--pin-tag",
            "stable",
            "--mark-changed-on-tag-move",
        ]
        with (
            patch.object(sut, "ensure_dir"),
            patch.object(sut, "is_git_repo", return_value=True),
            patch.object(sut, "remote_exists", return_value=True),
            patch.object(sut, "fetch_branch_shallow"),
            patch.object(sut, "get_local_tag_commit", return_value="111"),
            patch.object(sut, "resolve_remote_tag_commit", return_value="222"),
            patch.object(sut, "fetch_tag_shallow"),
            patch.object(sut, "checkout_detached"),
            patch("sys_util_git_pull.sys.argv", argv),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = sut.main()
            self.assertEqual(0, rc)
            self.assertIn("CHANGED=true", out.getvalue())
            self.assertIn("TAG_MOVED=true", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
