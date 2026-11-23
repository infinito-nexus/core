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
SLOTS_MODULE = "cli.administration.deploy.development.slots"


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


def _max_slot() -> str:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; printf %s "$WORKTREE_MAX_SLOT"', "bash", str(LIB)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _shim(bin_dir: Path, name: str, body: str) -> None:
    shim = bin_dir / name
    shim.write_text(f"#!/bin/sh\n{body}\n")
    shim.chmod(0o755)


class SlotShims:
    def __init__(
        self,
        tmp: str,
        checkouts: tuple[str, ...],
        subnets: tuple[str, ...],
        docker_exit: int = 0,
        git_exit: int = 0,
    ) -> None:
        root = Path(tmp)
        listing = root / "listing"
        listing.write_text("".join(f"worktree {c}\nHEAD 0\n\n" for c in checkouts))
        networks = root / "networks"
        networks.write_text("".join(f"{subnet}\n" for subnet in subnets))
        self.argv = root / "python3.argv"
        bin_dir = root / "bin"
        bin_dir.mkdir()
        _shim(bin_dir, "git", f'[ {git_exit} = 0 ] || exit {git_exit}\ncat "{listing}"')
        _shim(
            bin_dir,
            "docker",
            f"[ {docker_exit} = 0 ] || exit {docker_exit}\n"
            f'if [ "$2" = ls ]; then echo n1; else cat "{networks}"; fi',
        )
        _shim(bin_dir, "python3", f'printf "%s\\n" "$@" > "{self.argv}"\necho 7')
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    def call(self, func: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", f'source "$1"; shift; {func} "$@"', "bash", str(LIB), *args],
            capture_output=True,
            text=True,
            check=False,
            env=self.env,
        )

    def python_argv(self) -> list[str] | None:
        if not self.argv.exists():
            return None
        return read_text(str(self.argv)).splitlines()


class TestWorktreeTakenSlots(unittest.TestCase):
    def taken(self, subnets: tuple[str, ...], docker_exit: int = 0) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            shims = SlotShims(tmp, (), subnets, docker_exit=docker_exit)
            result = shims.call("worktree_taken_slots")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.split()

    def test_a_compose_subnet_holds_its_slot(self) -> None:
        self.assertEqual(self.taken(("172.30.2.0/24",)), ["2"])

    def test_a_swarm_lab_subnet_holds_its_slot(self) -> None:
        self.assertEqual(self.taken(("10.160.1.0/24",)), ["1"])

    def test_a_longer_slot_number_does_not_hold_its_prefix(self) -> None:
        self.assertEqual(self.taken(("172.30.10.0/24",)), ["10"])

    def test_foreign_subnets_hold_no_slot(self) -> None:
        self.assertEqual(self.taken(("192.168.1.0/24", "10.47.0.0/24")), [])

    def test_a_failing_docker_holds_no_slot(self) -> None:
        self.assertEqual(self.taken(("172.30.1.0/24",), docker_exit=1), [])


class TestWorktreeSlotRegistryCalls(unittest.TestCase):
    def test_allocation_hands_the_registry_every_worktree_and_held_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shims = SlotShims(
                tmp, ("/main", "/wt/feat"), ("172.30.3.0/24", "10.160.5.0/24")
            )
            result = shims.call("worktree_allocate_slot", "/wt/new")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "7\n")
            self.assertEqual(
                shims.python_argv(),
                [
                    "-m",
                    SLOTS_MODULE,
                    "allocate",
                    "/wt/new",
                    "--last",
                    _max_slot(),
                    "--known",
                    "/main",
                    "/wt/feat",
                    "--taken",
                    "3",
                    "5",
                ],
            )

    def test_allocation_without_networks_passes_an_empty_taken_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shims = SlotShims(tmp, ("/main",), ())
            result = shims.call("worktree_allocate_slot", "/wt/new")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(shims.python_argv()[-3:], ["--known", "/main", "--taken"])

    def test_an_unlistable_repository_allocates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shims = SlotShims(tmp, ("/main",), (), git_exit=128)
            result = shims.call("worktree_allocate_slot", "/wt/new")
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(shims.python_argv())

    def test_release_hands_the_registry_the_removed_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shims = SlotShims(tmp, (), ())
            result = shims.call("worktree_release_slots", "/wt/gone")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                shims.python_argv(), ["-m", SLOTS_MODULE, "release", "/wt/gone"]
            )


class TestUpScript(unittest.TestCase):
    def test_the_slot_is_allocated_once_the_checkout_exists(self) -> None:
        up_sh = read_text(str(LIB.parent / "up.sh"))
        added = up_sh.index('git worktree add "${path}" "${branch}"')
        allocated = up_sh.index('slot="$(worktree_allocate_slot "${path}")"')
        pinned = up_sh.index("INFINITO_INSTANCE=${slot}")
        self.assertLess(added, allocated)
        self.assertLess(allocated, pinned)

    def test_a_refused_slot_is_reported_before_the_worktree_is_removed(self) -> None:
        up_sh = read_text(str(LIB.parent / "up.sh"))
        reported = up_sh.index("FAILURE: the slot registry gave ${path} no slot")
        removed = up_sh.index('if git worktree remove --force "${path}"; then')
        self.assertLess(reported, removed)

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

    def test_the_last_slot_keeps_a_valid_bind_ip(self) -> None:
        self.assertLessEqual(int(_max_slot()) + 1, 255)


if __name__ == "__main__":
    unittest.main()
