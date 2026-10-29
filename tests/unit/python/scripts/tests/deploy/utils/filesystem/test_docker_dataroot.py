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
    "  mountpoint) exit 1 ;;\n"
    '  zpool) [ "$1" != list ] ;;\n'
    '  systemctl) [ "$1" != cat ] ;;\n'
    "  python3) cat >/dev/null ;;\n"
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
)


def apply_zfs() -> tuple[subprocess.CompletedProcess, list[list[str]]]:
    """Run the zfs path of docker_dataroot.sh against stubs of every host tool.

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
            ["bash", str(SCRIPT), "zfs", "true", "30G", "unit-node"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = [line.split() for line in read_text(str(log)).splitlines()]
        return done, calls


class TestDockerDatarootZfs(unittest.TestCase):
    def test_the_stubbed_zfs_path_applies(self) -> None:
        done, _ = apply_zfs()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("status=applied-pending-docker", done.stdout)

    def test_the_pool_returns_freed_blocks_to_the_sparse_image(self) -> None:
        _, calls = apply_zfs()
        creates = [argv for argv in calls if argv[:2] == ["zpool", "create"]]
        self.assertEqual(len(creates), 1, calls)
        self.assertIn(("-o", "autotrim=on"), list(pairwise(creates[0])))


if __name__ == "__main__":
    unittest.main()
