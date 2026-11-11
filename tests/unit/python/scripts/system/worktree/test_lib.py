"""Contract of the shared worktree metadata helpers.

``worktree_unregister`` is what lets a teardown succeed under the agent sandbox,
which pins some files inside ``.git/worktrees/<id>`` as read-only bind mounts so
the directory cannot be unlinked. Its three outcomes drive both callers: fully
removed, unregistered but pinned, and still registered. The last one is the only
state that keeps a branch claimed, so it must never be reported as success.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

LIB = PROJECT_ROOT / "scripts" / "system" / "worktree" / "lib.sh"
NEEDS_UNPRIVILEGED = "clearing the write bit does not restrain root"


def _call(func: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'source "$1"; shift; {func} "$@"', "bash", str(LIB), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestWorktreeMetaDir(unittest.TestCase):
    def test_reads_the_gitdir_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".git").write_text("gitdir: /somewhere/.git/worktrees/feat\n")
            result = _call("worktree_meta_dir", tmp)
        self.assertEqual(result.stdout.strip(), "/somewhere/.git/worktrees/feat")

    def test_missing_git_file_yields_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _call("worktree_meta_dir", tmp)
        self.assertEqual(result.stdout.strip(), "")

    def test_directory_git_yields_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".git").mkdir()
            result = _call("worktree_meta_dir", tmp)
        self.assertEqual(result.stdout.strip(), "")


class TestWorktreeUnregister(unittest.TestCase):
    def _entry(self, tmp: str) -> Path:
        entry = Path(tmp) / "feat"
        entry.mkdir()
        (entry / "gitdir").write_text("/checkout/.git\n")
        (entry / "HEAD").write_text("ref: refs/heads/feat\n")
        (entry / "commondir").write_text("../..\n")
        return entry

    def test_removes_the_whole_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = self._entry(tmp)
            result = _call("worktree_unregister", str(entry))
            self.assertEqual(result.returncode, 0)
            self.assertFalse(entry.exists())

    @unittest.skipIf(os.geteuid() == 0, NEEDS_UNPRIVILEGED)
    def test_pinned_directory_still_unregisters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = self._entry(tmp)
            tmp_path = Path(tmp)
            parent_mode = tmp_path.stat().st_mode
            (entry / "gitdir").unlink()
            (entry / "HEAD").unlink()
            tmp_path.chmod(parent_mode & ~stat.S_IWUSR)
            try:
                result = _call("worktree_unregister", str(entry))
            finally:
                tmp_path.chmod(parent_mode)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(entry.exists())

    @unittest.skipIf(os.geteuid() == 0, NEEDS_UNPRIVILEGED)
    def test_undeletable_pointers_report_still_registered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = self._entry(tmp)
            mode = entry.stat().st_mode
            entry.chmod(mode & ~stat.S_IWUSR)
            try:
                result = _call("worktree_unregister", str(entry))
            finally:
                entry.chmod(mode)
            self.assertEqual(result.returncode, 2)
            self.assertTrue((entry / "gitdir").exists())

    def test_is_idempotent_on_a_half_emptied_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = self._entry(tmp)
            (entry / "HEAD").unlink()
            result = _call("worktree_unregister", str(entry))
            self.assertEqual(result.returncode, 0)
            self.assertFalse(entry.exists())


DOCKER_STUB = """#!/usr/bin/env bash
[ "${STUB_EXIT}" = 0 ] || exit "${STUB_EXIT}"
case "$1 $2" in
"network ls") printf 'net-a\\nnet-b\\n' ;;
"network inspect") printf '%s\\n' ${STUB_SUBNETS} ;;
esac
"""


class TestWorktreeNextSlot(unittest.TestCase):
    def _next_slot(self, subnets: str, *, docker_exit: int = 0) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            stub = Path(tmp) / "bin" / "docker"
            stub.parent.mkdir()
            stub.write_text(DOCKER_STUB)
            stub.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}",
                "STUB_SUBNETS": subnets,
                "STUB_EXIT": str(docker_exit),
            }
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; worktree_next_slot', "bash", str(LIB)],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
        return result.stdout.strip()

    def test_free_subnet_takes_the_next_slot(self) -> None:
        self.assertEqual(self._next_slot("172.17.0.0/16"), "1")

    def test_leftover_network_on_the_compose_subnet_is_skipped(self) -> None:
        self.assertEqual(self._next_slot("172.17.0.0/16 172.30.1.0/24"), "2")

    def test_leftover_network_on_the_lab_subnet_is_skipped(self) -> None:
        self.assertEqual(self._next_slot("172.30.1.0/24 10.160.2.0/24"), "3")

    def test_negative_control_a_longer_slot_number_does_not_block(self) -> None:
        self.assertEqual(self._next_slot("172.30.10.0/24 172.30.11.0/24"), "1")

    def test_failing_docker_keeps_the_worktree_pick(self) -> None:
        self.assertEqual(self._next_slot("172.30.1.0/24", docker_exit=1), "1")

    def test_the_probed_prefixes_are_the_ones_up_sh_pins(self) -> None:
        up_sh = read_text(str(LIB.with_name("up.sh")))
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; printf "%s %s" "$WORKTREE_NET_PREFIX" "$WORKTREE_LAB_PREFIX"',
                "bash",
                str(LIB),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        net, lab = result.stdout.split()
        self.assertIn(f"INFINITO_SUBNET={net}.${{slot}}.0/24", up_sh)
        self.assertIn(f'lab_prefix="{lab}.${{slot}}"', up_sh)


if __name__ == "__main__":
    unittest.main()
