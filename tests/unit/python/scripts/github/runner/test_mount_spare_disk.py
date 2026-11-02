from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

SCRIPT = PROJECT_ROOT / "scripts" / "github" / "runner" / "mount_spare_disk.sh"
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test-deploy.yml"
MIN_SIZE_GB = "75"
GIB = 1024**3
SPARE = "nvme9n9"
SPARE_INDEX = 2
DESTRUCTIVE = ("mkfs.ext4", "blkid", "wipefs", "mount", "mkswap")

SUDO_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "$*" >>"${STUB_LOG}"\n'
    'if [ -x "${STUB_BIN}/$1" ]; then exec "${STUB_BIN}/$1" "${@:2}"; fi\n'
    'echo "unstubbed sudo $1" >&2\n'
    "exit 97\n"
)
UNPRIVILEGED_STUB = (
    '#!/usr/bin/env bash\necho "$(basename "$0") ran without sudo" >&2\nexit 98\n'
)
LSBLK_STUB = '#!/usr/bin/env bash\ncat "${STUB_LSBLK_JSON}"\n'
MOUNTPOINT_STUB = '#!/usr/bin/env bash\n[ "${STUB_MOUNTED}" = 1 ]\n'
BLKID_STUB = (
    '#!/usr/bin/env bash\nprintf "%s" "${STUB_BLKID_OUT}"\nexit "${STUB_BLKID_RC}"\n'
)
WIPEFS_STUB = '#!/usr/bin/env bash\nprintf "%s" "${STUB_WIPEFS_OUT}"\n'
MKFS_STUB = "#!/usr/bin/env bash\nexit 0\n"
MOUNT_STUB = (
    '#!/usr/bin/env bash\nprintf "%s" "${STUB_MOUNT_AS:-$1}" >"${STUB_STATE}"\n'
)
FINDMNT_STUB = '#!/usr/bin/env bash\ncat "${STUB_STATE}"\n'
DUMP_STUB = "#!/usr/bin/env bash\nexit 0\n"


def part(name: str, size_gib: float, fstype: str | None, mount: str | None) -> dict:
    """Build one lsblk partition entry.

    Args:
        name: kernel name of the partition.
        size_gib: size in GiB.
        fstype: filesystem type, None when unformatted.
        mount: mount point, None when unmounted.

    Returns:
        The entry as lsblk -J -b prints it.
    """
    return {
        "name": name,
        "type": "part",
        "size": int(size_gib * GIB),
        "ro": False,
        "fstype": fstype,
        "pttype": "gpt",
        "mountpoints": [mount],
    }


def snap_loops() -> list[dict]:
    """Return the two snap squashfs loop devices every runner shape carries.

    Returns:
        The loop entries as lsblk -J -b prints them.
    """
    return [
        {
            "name": f"loop{index}",
            "type": "loop",
            "size": 77594624,
            "ro": True,
            "fstype": "squashfs",
            "pttype": None,
            "mountpoints": [mount],
        }
        for index, mount in enumerate(("/snap/core22/2955", "/snap/snapd/28254"))
    ]


def root_disk(name: str, prefix: str, size_gib: int) -> dict:
    """Build the partitioned root disk of a GitHub runner image.

    Args:
        name: kernel name of the disk.
        prefix: partition name prefix (``sda`` or ``nvme0n1p``).
        size_gib: size in GiB.

    Returns:
        The disk entry with its four partitions.
    """
    return {
        "name": name,
        "type": "disk",
        "size": size_gib * GIB,
        "ro": False,
        "fstype": None,
        "pttype": "gpt",
        "mountpoints": [None],
        "children": [
            part(f"{prefix}1", size_gib - 1.2, "ext4", "/"),
            part(f"{prefix}13", 1, "ext4", "/boot"),
            part(f"{prefix}14", 0.004, None, None),
            part(f"{prefix}15", 0.1, "vfat", "/boot/efi"),
        ],
    }


def spare_disk(size_gib: int) -> dict:
    """Build the empty second NVMe disk of the small runner shape.

    Args:
        size_gib: size in GiB.

    Returns:
        The disk entry without filesystem, partition table or mount.
    """
    return {
        "name": SPARE,
        "type": "disk",
        "size": size_gib * GIB,
        "ro": False,
        "fstype": None,
        "pttype": None,
        "mountpoints": [None],
    }


LARGE_SHAPE = {"blockdevices": [*snap_loops(), root_disk("sda", "sda", 145)]}
SMALL_SHAPE = {
    "blockdevices": [
        *snap_loops(),
        spare_disk(128),
        root_disk("nvme0n1", "nvme0n1p", 72),
    ]
}


def with_spare(**changes: object) -> dict:
    """Return the small shape with fields of the spare disk replaced.

    Args:
        **changes: lsblk fields to overwrite on the spare disk.

    Returns:
        A modified deep copy of SMALL_SHAPE.
    """
    tree = copy.deepcopy(SMALL_SHAPE)
    tree["blockdevices"][SPARE_INDEX].update(changes)
    return tree


def run(
    tree: dict,
    *,
    runner_environment: str | None = "github-hosted",
    act: str | None = None,
    mounted: bool = False,
    blkid_rc: int = 2,
    blkid_out: str = "",
    wipefs_out: str = "",
    mount_as: str | None = None,
    occupied: bool = False,
    min_size_gb: str = MIN_SIZE_GB,
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run mount_spare_disk.sh against a faked block-device layout.

    Args:
        tree: what ``lsblk -J -b`` reports.
        runner_environment: RUNNER_ENVIRONMENT, None to leave it unset.
        act: ACT, None to leave it unset.
        mounted: whether the mount point already is a mount.
        blkid_rc: exit code of ``blkid -p`` (2 means no signature).
        blkid_out: what ``blkid -p`` prints.
        wipefs_out: what ``wipefs --no-act`` prints.
        mount_as: device findmnt reports after the mount, None for the mounted one.
        occupied: whether the mount point already holds a file.
        min_size_gb: the MIN_SIZE_GB argument.

    Returns:
        The finished process and every privileged call in order.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runner_dir = root / "runner"
        runner_dir.mkdir()
        (runner_dir / "mount_spare_disk.sh").symlink_to(SCRIPT)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub_bin = root / "privileged"
        stub_bin.mkdir()
        stubs = [
            (runner_dir / "dump_state.sh", DUMP_STUB),
            (bin_dir / "sudo", SUDO_STUB),
            (bin_dir / "lsblk", LSBLK_STUB),
            (bin_dir / "mountpoint", MOUNTPOINT_STUB),
            (bin_dir / "findmnt", FINDMNT_STUB),
            (stub_bin / "blkid", BLKID_STUB),
            (stub_bin / "wipefs", WIPEFS_STUB),
            (stub_bin / "mkfs.ext4", MKFS_STUB),
            (stub_bin / "mount", MOUNT_STUB),
        ]
        stubs += [(bin_dir / name, UNPRIVILEGED_STUB) for name in DESTRUCTIVE]
        for path, body in stubs:
            path.write_text(body)
            path.chmod(0o755)
        mount_point = root / "mnt"
        mount_point.mkdir()
        if occupied:
            (mount_point / "keep.txt").write_text("data\n")
        lsblk_json = root / "lsblk.json"
        lsblk_json.write_text(json.dumps(tree))
        log = root / "sudo.log"
        log.touch()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("BASH_ENV", "ACT", "RUNNER_ENVIRONMENT")
        }
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            STUB_BIN=str(stub_bin),
            STUB_LSBLK_JSON=str(lsblk_json),
            STUB_MOUNTED="1" if mounted else "0",
            STUB_BLKID_RC=str(blkid_rc),
            STUB_BLKID_OUT=blkid_out,
            STUB_WIPEFS_OUT=wipefs_out,
            STUB_STATE=str(root / "mounted-source"),
        )
        if mount_as is not None:
            env["STUB_MOUNT_AS"] = mount_as
        if runner_environment is not None:
            env["RUNNER_ENVIRONMENT"] = runner_environment
        if act is not None:
            env["ACT"] = act
        done = subprocess.run(
            [
                "bash",
                str(runner_dir / "mount_spare_disk.sh"),
                str(mount_point),
                min_size_gb,
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return done, log.read_text().splitlines()  # nocheck: cache-read  stub call log


def formatted(calls: list[str]) -> bool:
    """Tell whether any privileged call formatted or mounted a disk.

    Args:
        calls: every recorded sudo call.

    Returns:
        True when mkfs or mount ran.
    """
    return any(call.startswith(("mkfs", "mount ")) for call in calls)


class TestMountSpareDisk(unittest.TestCase):
    def assert_untouched(self, done: subprocess.CompletedProcess, reason: str) -> None:
        """Assert a declined run: exit 0, no privileged call, the stated reason.

        Args:
            done: the finished script.
            reason: text the script must print for this decline.
        """
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(reason, done.stdout + done.stderr)
        self.assertRegex(done.stdout, r"::(notice|warning)::")

    def test_small_shape_formats_and_mounts_the_empty_nvme_disk(self) -> None:
        done, calls = run(SMALL_SHAPE)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            calls[:3],
            [
                f"blkid -p /dev/{SPARE}",
                f"wipefs --no-act --noheadings /dev/{SPARE}",
                f"mkfs.ext4 -q -m 0 -L infinito-spare /dev/{SPARE}",
            ],
        )
        self.assertTrue(calls[3].startswith(f"mount /dev/{SPARE} "), calls)
        self.assertEqual(len(calls), 4, calls)

    def test_large_shape_without_a_spare_disk_stays_as_it_is(self) -> None:
        done, calls = run(LARGE_SHAPE)
        self.assert_untouched(done, '["sda"]')
        self.assertEqual(calls, [])

    def test_self_hosted_runner_is_never_formatted(self) -> None:
        done, calls = run(SMALL_SHAPE, runner_environment="self-hosted")
        self.assert_untouched(done, "not a GitHub-hosted runner")
        self.assertEqual(calls, [])

    def test_unknown_runner_environment_is_never_formatted(self) -> None:
        done, calls = run(SMALL_SHAPE, runner_environment=None)
        self.assert_untouched(done, "not a GitHub-hosted runner")
        self.assertEqual(calls, [])

    def test_act_refuses_loudly_even_with_a_faked_github_runner(self) -> None:
        for act in ("true", "1", "TRUE"):
            with self.subTest(act=act):
                done, calls = run(SMALL_SHAPE, act=act)
                self.assertEqual(done.returncode, 1)
                self.assertEqual(calls, [])
                self.assertIn("refuses to run under act", done.stderr)

    def test_disk_with_a_filesystem_is_never_formatted(self) -> None:
        done, calls = run(with_spare(fstype="ext4"))
        self.assert_untouched(done, "No empty, unpartitioned, unmounted disk")
        self.assertEqual(calls, [])

    def test_disk_with_partitions_is_never_formatted(self) -> None:
        done, calls = run(with_spare(children=[part(f"{SPARE}p1", 127, None, None)]))
        self.assert_untouched(done, "No empty, unpartitioned, unmounted disk")
        self.assertEqual(calls, [])

    def test_disk_held_by_lvm_is_never_formatted(self) -> None:
        holder = {
            "name": "vg-data",
            "type": "lvm",
            "size": 127 * GIB,
            "ro": False,
            "fstype": None,
            "pttype": None,
            "mountpoints": [None],
        }
        done, calls = run(with_spare(children=[holder]))
        self.assert_untouched(done, "No empty, unpartitioned, unmounted disk")
        self.assertEqual(calls, [])

    def test_disk_with_a_bare_partition_table_is_never_formatted(self) -> None:
        done, calls = run(with_spare(pttype="dos"))
        self.assert_untouched(done, "No empty, unpartitioned, unmounted disk")
        self.assertEqual(calls, [])

    def test_mounted_disk_is_never_formatted(self) -> None:
        done, calls = run(with_spare(mountpoints=["/data"]))
        self.assert_untouched(done, "No empty, unpartitioned, unmounted disk")
        self.assertEqual(calls, [])

    def test_disk_used_as_swap_is_never_formatted(self) -> None:
        done, calls = run(with_spare(mountpoints=["[SWAP]"]))
        self.assert_untouched(done, "No empty, unpartitioned, unmounted disk")
        self.assertEqual(calls, [])

    def test_read_only_disk_is_never_formatted(self) -> None:
        done, calls = run(with_spare(ro=True))
        self.assert_untouched(done, "No empty, unpartitioned, unmounted disk")
        self.assertEqual(calls, [])

    def test_disk_below_the_size_floor_stays_as_it_is(self) -> None:
        done, calls = run(with_spare(size=32 * GIB))
        self.assert_untouched(done, "No empty, unpartitioned, unmounted disk")
        self.assertEqual(calls, [])

    def test_signature_lsblk_missed_is_never_formatted(self) -> None:
        done, calls = run(SMALL_SHAPE, blkid_rc=0, blkid_out='TYPE="xfs"')
        self.assert_untouched(done, "carries a signature")
        self.assertFalse(formatted(calls), calls)

    def test_signature_only_wipefs_sees_is_never_formatted(self) -> None:
        done, calls = run(SMALL_SHAPE, wipefs_out="0x218 LVM2_member")
        self.assert_untouched(done, "carries signatures blkid missed")
        self.assertFalse(formatted(calls), calls)

    def test_inconclusive_probe_fails_loudly_without_formatting(self) -> None:
        done, calls = run(SMALL_SHAPE, blkid_rc=8, blkid_out="ambivalent result")
        self.assertEqual(done.returncode, 1)
        self.assertFalse(formatted(calls), calls)

    def test_probe_that_found_nothing_but_complained_fails_loudly(self) -> None:
        done, calls = run(SMALL_SHAPE, blkid_rc=2, blkid_out="Input/output error")
        self.assertEqual(done.returncode, 1)
        self.assertFalse(formatted(calls), calls)

    def test_lsblk_without_mountpoints_fails_loudly(self) -> None:
        tree = copy.deepcopy(SMALL_SHAPE)
        spare = tree["blockdevices"][SPARE_INDEX]
        spare["mountpoint"] = spare.pop("mountpoints")[0]
        done, calls = run(tree)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(calls, [])

    def test_layout_without_a_root_device_fails_loudly(self) -> None:
        done, calls = run({"blockdevices": [spare_disk(128)]})
        self.assertEqual(done.returncode, 1)
        self.assertEqual(calls, [])

    def test_non_numeric_size_floor_fails_loudly(self) -> None:
        done, calls = run(SMALL_SHAPE, min_size_gb="RANDOM")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(calls, [])

    def test_existing_mount_stays_as_it_is(self) -> None:
        done, calls = run(SMALL_SHAPE, mounted=True)
        self.assert_untouched(done, "already a separate mount")
        self.assertEqual(calls, [])

    def test_occupied_mount_point_stays_as_it_is(self) -> None:
        done, calls = run(SMALL_SHAPE, occupied=True)
        self.assert_untouched(done, "is not empty")
        self.assertEqual(calls, [])

    def test_mount_landing_on_another_device_fails_loudly(self) -> None:
        done, _ = run(SMALL_SHAPE, mount_as="/dev/nvme0n1p1")
        self.assertEqual(done.returncode, 1)
        self.assertIn("backed by '/dev/nvme0n1p1'", done.stderr)


class TestWorkflowWiring(unittest.TestCase):
    def test_spare_disk_step_is_act_gated_and_runs_before_swap_and_relocation(
        self,
    ) -> None:
        workflow = load_yaml(str(WORKFLOW))
        steps = next(
            job["steps"]
            for job in workflow["jobs"].values()
            if any(
                "mount_spare_disk.sh" in str(step.get("run", ""))
                for step in job.get("steps", [])
            )
        )
        runs = [str(step.get("run", "")) for step in steps]
        index = next(i for i, cmd in enumerate(runs) if "mount_spare_disk.sh" in cmd)
        self.assertEqual(
            runs[index],
            f"./scripts/github/runner/mount_spare_disk.sh /mnt {MIN_SIZE_GB}",
        )
        self.assertEqual(steps[index].get("if"), "${{ !env.ACT }}")
        swap = next(i for i, cmd in enumerate(runs) if "enlarge_swap.sh" in cmd)
        relocate = next(
            i for i, cmd in enumerate(runs) if "relocate_docker_dataroot.sh" in cmd
        )
        self.assertLess(index, relocate)
        self.assertLess(relocate, swap)
        self.assertEqual(
            runs[relocate], "./scripts/github/runner/relocate_docker_dataroot.sh 75"
        )
        self.assertEqual(steps[relocate].get("if"), "${{ !env.ACT }}")


if __name__ == "__main__":
    unittest.main()
