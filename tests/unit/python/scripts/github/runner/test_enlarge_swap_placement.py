from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "github" / "runner" / "enlarge_swap.sh"
SUDO_STUB = '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"${STUB_LOG}"\n'
DF_STUB = (
    "#!/usr/bin/env bash\n"
    'echo "Avail"\n'
    'if [ "${*: -1}" = /mnt ]; then echo "${STUB_MNT_FREE}"; else echo "${STUB_ROOT_FREE}"; fi\n'
)
MOUNTPOINT_STUB = '#!/usr/bin/env bash\n[ "${STUB_MNT_MOUNTED}" = 1 ]\n'
STAT_STUB = (
    "#!/usr/bin/env bash\n"
    'case "${*: -1}" in\n'
    "/mnt) echo 2049 ;;\n"
    '/var/lib/containerd) if [ "${STUB_CONTAINERD_DEV}" = missing ]; then exit 1; fi\n'
    '  echo "${STUB_CONTAINERD_DEV}" ;;\n'
    "*) exit 1 ;;\n"
    "esac\n"
)
DUMP_STUB = "#!/usr/bin/env bash\nexit 0\n"


def enlarge(
    *, mounted: bool, mnt_free: int, root_free: int, containerd_dev: str
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run enlarge_swap.sh against stubbed disks.

    Args:
        mounted: whether /mnt is a separate mount.
        mnt_free: GB df reports free on /mnt.
        root_free: GB df reports free on /.
        containerd_dev: device id stat reports for /var/lib/containerd
            (2049 is the /mnt device).

    Returns:
        The finished process and every sudo call in order.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runner_dir = root / "runner"
        runner_dir.mkdir()
        (runner_dir / "enlarge_swap.sh").symlink_to(SCRIPT)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for path, body in (
            (runner_dir / "dump_state.sh", DUMP_STUB),
            (bin_dir / "sudo", SUDO_STUB),
            (bin_dir / "df", DF_STUB),
            (bin_dir / "mountpoint", MOUNTPOINT_STUB),
            (bin_dir / "stat", STAT_STUB),
        ):
            path.write_text(body)
            path.chmod(0o755)
        log = root / "sudo.log"
        log.touch()
        env = {
            k: v for k, v in os.environ.items() if k not in ("BASH_ENV", "SKIP_SWAP")
        }
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            STUB_MNT_MOUNTED="1" if mounted else "0",
            STUB_MNT_FREE=str(mnt_free),
            STUB_ROOT_FREE=str(root_free),
            STUB_CONTAINERD_DEV=containerd_dev,
        )
        done = subprocess.run(
            ["bash", str(runner_dir / "enlarge_swap.sh")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return done, log.read_text().splitlines()  # nocheck: cache-read  stub call log


def swapfile(calls: list[str]) -> list[str]:
    """Return the fallocate calls among the recorded sudo calls.

    Args:
        calls: every recorded sudo call.

    Returns:
        The calls that create the swapfile.
    """
    return [call for call in calls if call.startswith("fallocate ")]


class TestEnlargeSwapPlacement(unittest.TestCase):
    def test_swap_goes_to_root_when_containerd_lives_on_the_spare_disk(self) -> None:
        done, calls = enlarge(
            mounted=True, mnt_free=200, root_free=54, containerd_dev="2049"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(swapfile(calls), ["fallocate -l 16G /swapfile"])

    def test_swap_goes_to_mnt_when_containerd_stayed_on_root(self) -> None:
        done, calls = enlarge(
            mounted=True, mnt_free=60, root_free=54, containerd_dev="66305"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(swapfile(calls), ["fallocate -l 16G /mnt/swapfile"])

    def test_large_shape_without_mnt_keeps_swap_on_root(self) -> None:
        done, calls = enlarge(
            mounted=False, mnt_free=0, root_free=123, containerd_dev="66305"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(swapfile(calls), ["fallocate -l 16G /swapfile"])

    def test_missing_containerd_root_keeps_the_mnt_preference(self) -> None:
        done, calls = enlarge(
            mounted=True, mnt_free=60, root_free=54, containerd_dev="missing"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(swapfile(calls), ["fallocate -l 16G /mnt/swapfile"])

    def test_full_root_still_uses_the_spare_disk(self) -> None:
        done, calls = enlarge(
            mounted=True, mnt_free=200, root_free=10, containerd_dev="2049"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(swapfile(calls), ["fallocate -l 16G /mnt/swapfile"])


if __name__ == "__main__":
    unittest.main()
