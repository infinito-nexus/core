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


def _shim(bin_dir: Path, name: str, body: str) -> None:
    shim = bin_dir / name
    shim.write_text(f"#!/bin/sh\n{body}\n")
    shim.chmod(0o755)


def _next_slot(tmp: str, slots: list[int], subnets: tuple[str, ...] = ()) -> str:
    root = Path(tmp)
    lines = []
    for index, slot in enumerate(slots):
        checkout = root / f"checkout-{index}"
        checkout.mkdir()
        if slot:
            (checkout / "custom.env").write_text(f"INFINITO_INSTANCE={slot}\n")
        lines.append(f"worktree {checkout}\n")
    listing = root / "listing"
    listing.write_text("".join(lines))
    networks = root / "networks"
    networks.write_text("".join(f"{subnet}\n" for subnet in subnets))
    bin_dir = root / "bin"
    bin_dir.mkdir()
    _shim(bin_dir, "git", f'cat "{listing}"')
    _shim(
        bin_dir,
        "docker",
        f'if [ "$2" = ls ]; then echo n1; else cat "{networks}"; fi',
    )
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; worktree_next_slot', "bash", str(LIB)],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout


class TestWorktreeNextSlot(unittest.TestCase):
    def test_reuses_the_lowest_free_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_next_slot(tmp, [0, 1, 2, 4, 9]), "3")

    def test_an_unpinned_primary_alone_gets_slot_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_next_slot(tmp, [0]), "1")

    def test_skips_a_slot_whose_compose_subnet_a_network_holds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_next_slot(tmp, [0, 1], ("172.30.2.0/24",)), "3")

    def test_skips_a_slot_whose_swarm_lab_subnet_a_network_holds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_next_slot(tmp, [0], ("10.160.1.0/24",)), "2")

    def test_a_longer_slot_number_does_not_hold_its_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_next_slot(tmp, [0], ("172.30.10.0/24",)), "1")

    def test_the_prefixes_match_the_pins_up_sh_writes(self) -> None:
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
        up_sh = read_text(str(LIB.parent / "up.sh"))
        self.assertIn(f"INFINITO_SUBNET={net}.${{slot}}.0/24", up_sh)
        self.assertIn(f'lab_prefix="{lab}.${{slot}}"', up_sh)

    def test_a_full_range_reports_past_the_last_valid_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_next_slot(tmp, list(range(255))), "255")

    def test_the_last_slot_keeps_a_valid_bind_ip(self) -> None:
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; printf %s "$WORKTREE_MAX_SLOT"',
                "bash",
                str(LIB),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertLessEqual(int(result.stdout) + 1, 255)


if __name__ == "__main__":
    unittest.main()
