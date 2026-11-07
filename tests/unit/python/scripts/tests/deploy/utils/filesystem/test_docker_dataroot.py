from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from itertools import pairwise
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

SCRIPT = (
    PROJECT_ROOT
    / "scripts"
    / "tests"
    / "deploy"
    / "utils"
    / "filesystem"
    / "docker_dataroot.sh"
)
STUB = (
    "#!/usr/bin/env bash\n"
    'name="$(basename "$0")"\n'
    'printf "%s %s\\n" "${name}" "$*" >>"${STUB_LOG}"\n'
    'case "${name}" in\n'
    "  id) echo 0 ;;\n"
    "  awk) echo 10 ;;\n"
    "  losetup) echo /dev/infinito-test-loop ;;\n"
    "  mountpoint) grep -q '^mount ' \"${STUB_LOG}\" ;;\n"
    '  zpool) [ "$1" != list ] ;;\n'
    '  systemctl) [ "$1" != cat ] ;;\n'
    "  python3|tee) cat >/dev/null ;;\n"
    "esac\n"
)
STUBBED = (
    "id",
    "awk",
    "losetup",
    "mountpoint",
    "zpool",
    "zfs",
    "systemctl",
    "python3",
    "modprobe",
    "mknod",
    "mkdir",
    "rm",
    "truncate",
    "install",
    "tee",
    "mount",
    "mkfs.ext4",
    "mkfs.btrfs",
    "btrfs",
)


def apply_fstype(fstype: str) -> tuple[subprocess.CompletedProcess, list[list[str]]]:
    """Run one path of docker_dataroot.sh against stubs of every host tool.

    Args:
        fstype: the filesystem the script puts the data root on.

    Returns:
        The finished process and the argv of every stubbed call, tool first.
    """
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        for name in STUBBED:
            stub = bin_dir / name
            stub.write_text(STUB)
            stub.chmod(0o755)
        log = Path(tmp) / "calls.log"
        log.touch()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("BASH_ENV", "GITHUB_STEP_SUMMARY")
        }
        env.update(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", STUB_LOG=str(log))
        done = subprocess.run(
            ["bash", str(SCRIPT), fstype, "true", "30G", "unit-node"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = [line.split() for line in read_text(str(log)).splitlines()]
        return done, calls


class TestDockerDatarootZfs(unittest.TestCase):
    def test_the_stubbed_zfs_path_applies(self) -> None:
        done, _ = apply_fstype("zfs")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("status=applied-pending-docker", done.stdout)

    def test_the_pool_returns_freed_blocks_to_the_sparse_image(self) -> None:
        _, calls = apply_fstype("zfs")
        creates = [argv for argv in calls if argv[:2] == ["zpool", "create"]]
        self.assertEqual(len(creates), 1, calls)
        self.assertIn(("-o", "autotrim=on"), list(pairwise(creates[0])))


class TestDockerDatarootLoopMount(unittest.TestCase):
    def _mounts(self, fstype: str) -> list[list[str]]:
        done, calls = apply_fstype(fstype)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        mounts = [argv for argv in calls if argv[0] == "mount"]
        self.assertEqual(len(mounts), 1, calls)
        return mounts

    def test_ext4_returns_freed_blocks_to_the_sparse_image(self) -> None:
        self.assertIn(("-o", "discard"), list(pairwise(self._mounts("ext4")[0])))

    def test_btrfs_keeps_the_discard_mode_of_the_kernel(self) -> None:
        self.assertNotIn("discard", self._mounts("btrfs")[0])


if __name__ == "__main__":
    unittest.main()
