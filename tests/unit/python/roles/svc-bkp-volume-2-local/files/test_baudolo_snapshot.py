#!/usr/bin/env python3
import importlib.util
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock

from . import PROJECT_ROOT

MOUNTINFO = (
    "23 1 0:20 / / rw,relatime - btrfs /dev/sda2 rw,subvol=/@\n"
    "31 23 0:20 /@docker /var/lib/docker rw,relatime - btrfs /dev/sda2 rw,subvol=/@docker\n"
    "44 31 0:52 / /var/lib/docker/volumes/nfs_vol/_data rw,relatime - nfs4 srv:/export rw\n"
    "45 23 0:60 / /mnt/with\\040space rw,relatime - ext4 /dev/sdb1 rw\n"
)


def load_target_module():
    script_path = (
        PROJECT_ROOT
        / "roles"
        / "svc-bkp-volume-2-local"
        / "files"
        / "python"
        / "baudolo_snapshot.py"
    )
    if not script_path.is_file():
        raise FileNotFoundError(f"Target script not found at: {script_path}")
    spec = importlib.util.spec_from_file_location("baudolo_snapshot", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SCRIPT = load_target_module()
DOCKER = SCRIPT.Subject("/var/lib/docker", Path("/var/lib/docker"))


def mounts():
    with tempfile.NamedTemporaryFile("w", suffix=".mountinfo", delete=False) as handle:
        handle.write(MOUNTINFO)
        path = Path(handle.name)
    with mock.patch.object(SCRIPT, "MOUNTINFO", path):
        return SCRIPT.read_mounts()


def volume(name, driver="local", options=None, mountpoint=None):
    return SCRIPT.Volume(
        name,
        driver,
        options or {},
        f"/var/lib/docker/volumes/{name}/_data" if mountpoint is None else mountpoint,
    )


class TestMountinfo(TestCase):
    def test_it_unescapes_a_mountpoint_holding_a_space(self):
        self.assertIn(Path("/mnt/with space"), [m.point for m in mounts()])

    def test_it_returns_the_deepest_mount_covering_a_path(self):
        found = SCRIPT.mount_of(Path("/var/lib/docker/volumes/a/_data"), mounts())
        self.assertEqual(found.point, Path("/var/lib/docker"))

    def test_it_returns_the_root_mount_for_an_unmounted_path(self):
        self.assertEqual(
            SCRIPT.mount_of(Path("/etc/hostname"), mounts()).point, Path("/")
        )


class TestVolumesReason(TestCase):
    def guard(self, declared):
        with mock.patch.object(SCRIPT, "volumes", return_value=declared):
            return SCRIPT.volumes_reason(DOCKER, mounts())

    def test_a_volume_declaring_nfs_is_refused_even_while_unmounted(self):
        reason = self.guard([volume("shared", options={"type": "nfs"})])
        self.assertIn("declares its own backing store", reason)

    def test_a_foreign_driver_is_refused(self):
        self.assertIn("driver", self.guard([volume("csi", driver="cluster")]))

    def test_a_volume_on_its_own_mount_is_refused(self):
        self.assertIn("sits on its own mount", self.guard([volume("nfs_vol")]))

    def test_a_volume_outside_the_subject_is_refused(self):
        reason = self.guard([volume("stray", mountpoint="/srv/data")])
        self.assertIn("lies outside", reason)

    def test_a_volume_without_a_mountpoint_is_refused(self):
        self.assertIn("no mountpoint", self.guard([volume("empty", mountpoint="")]))

    def test_an_unreadable_volume_list_is_refused(self):
        self.assertIn("could not be read", self.guard(None))


class TestBtrfsReason(TestCase):
    def test_a_plain_directory_is_refused(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(SCRIPT.shutil, "which", return_value="/usr/bin/btrfs"),
        ):
            subject = SCRIPT.Subject(tmp, Path(tmp))
            reason = SCRIPT.btrfs_reason(subject, mounts())
        self.assertIn("not a btrfs subvolume root", reason)

    def test_a_missing_btrfs_command_is_refused(self):
        with mock.patch.object(SCRIPT.shutil, "which", return_value=None):
            reason = SCRIPT.btrfs_reason(DOCKER, mounts())
        self.assertIn("btrfs command is not installed", reason)


class TestZfsReason(TestCase):
    def test_a_subdirectory_of_a_dataset_is_refused(self):
        with (
            mock.patch.object(SCRIPT.shutil, "which", return_value="/usr/sbin/zfs"),
            mock.patch.object(SCRIPT, "in_init_mount_namespace", return_value=True),
            mock.patch.object(SCRIPT, "run", return_value="tank/docker\t/tank\n"),
        ):
            reason = SCRIPT.zfs_reason(DOCKER, mounts())
        self.assertIn("not the mountpoint of a zfs dataset", reason)

    def test_a_foreign_mount_namespace_is_refused(self):
        with (
            mock.patch.object(SCRIPT.shutil, "which", return_value="/usr/sbin/zfs"),
            mock.patch.object(SCRIPT, "in_init_mount_namespace", return_value=False),
        ):
            reason = SCRIPT.zfs_reason(DOCKER, mounts())
        self.assertIn("init mount namespace", reason)


class TestDetect(TestCase):
    def test_auto_declines_a_filesystem_without_snapshots(self):
        subject = SCRIPT.Subject("/mnt/with space", Path("/mnt/with space"))
        kind, reason = SCRIPT.detect(subject, mounts())
        self.assertIsNone(kind)
        self.assertIn("takes no snapshots", reason)


class TestSnapshotFlags(TestCase):
    def probe(self, mode, **patches):
        defaults = {"docker_root": DOCKER, "volumes": []}
        defaults.update(patches)
        with (
            mock.patch.object(SCRIPT.os, "geteuid", return_value=0),
            mock.patch.object(SCRIPT, "reap"),
            mock.patch.object(
                SCRIPT, "docker_root", return_value=defaults["docker_root"]
            ),
            mock.patch.object(SCRIPT, "volumes", return_value=defaults["volumes"]),
            mock.patch.object(SCRIPT, "read_mounts", return_value=mounts()),
        ):
            return SCRIPT.guarded_flags(mode)

    def test_a_stated_kind_is_emitted_with_the_verbatim_subject(self):
        with mock.patch.dict(SCRIPT.CHECKS, {"btrfs": lambda *_: None}):
            flags = self.probe("btrfs")
        self.assertEqual(
            flags, ["--snapshot", "btrfs", "--snapshot-subject", "/var/lib/docker"]
        )

    def test_a_stated_kind_still_runs_the_volume_guard(self):
        with (
            mock.patch.dict(SCRIPT.CHECKS, {"btrfs": lambda *_: None}),
            self.assertRaises(SystemExit),
        ):
            self.probe("btrfs", volumes=[volume("shared", options={"type": "nfs"})])

    def test_a_stated_kind_aborts_instead_of_copying_live(self):
        with (
            mock.patch.object(SCRIPT, "docker_root", return_value=None),
            self.assertRaises(SystemExit),
        ):
            SCRIPT.guarded_flags("btrfs")

    def test_a_stated_kind_requires_root(self):
        with (
            mock.patch.object(SCRIPT, "docker_root", return_value=DOCKER),
            mock.patch.object(SCRIPT.os, "geteuid", return_value=1000),
            self.assertRaises(SystemExit),
        ):
            SCRIPT.guarded_flags("btrfs")

    def test_an_unresolvable_docker_root_falls_back_under_auto(self):
        with mock.patch.object(SCRIPT, "docker_root", return_value=None):
            self.assertEqual(SCRIPT.guarded_flags("auto"), [])

    def test_a_subject_baudolo_cannot_quote_falls_back_under_auto(self):
        odd = SCRIPT.Subject("/var/lib/my docker", Path("/var/lib/my docker"))
        with mock.patch.object(SCRIPT, "docker_root", return_value=odd):
            self.assertEqual(SCRIPT.guarded_flags("auto"), [])

    def test_an_unexpected_probe_error_falls_back_under_auto(self):
        with (
            mock.patch.object(SCRIPT, "docker_root", return_value=DOCKER),
            mock.patch.object(SCRIPT.os, "geteuid", return_value=0),
            mock.patch.object(SCRIPT, "read_mounts", side_effect=RuntimeError("boom")),
        ):
            self.assertEqual(SCRIPT.guarded_flags("auto"), [])


class TestArgv(TestCase):
    def test_it_drops_hard_restart_and_its_values(self):
        command = [
            "baudolo",
            "--only-sql",
            "--hard-restart-projects",
            "mailu",
            "nextcloud",
            "--backups-dir",
            "/b",
        ]
        self.assertEqual(
            SCRIPT.without_hard_restart(command),
            ["baudolo", "--only-sql", "--backups-dir", "/b"],
        )

    def test_it_leaves_a_command_without_hard_restart_alone(self):
        command = ["baudolo", "--only-sql"]
        self.assertEqual(SCRIPT.without_hard_restart(command), command)

    def test_never_execs_the_command_unchanged(self):
        argv = [
            "baudolo-snapshot",
            "--mode",
            "never",
            "--",
            "baudolo",
            "--only-sql",
        ]
        with (
            mock.patch.object(SCRIPT.sys, "argv", argv),
            mock.patch.object(SCRIPT, "guarded_flags") as flags,
            mock.patch.object(SCRIPT.os, "execvp") as execvp,
        ):
            SCRIPT.main()
        flags.assert_not_called()
        execvp.assert_called_once_with("baudolo", ["baudolo", "--only-sql"])

    def test_a_missing_separator_is_a_wiring_error(self):
        with (
            mock.patch.object(
                SCRIPT.sys, "argv", ["baudolo-snapshot", "--mode", "auto"]
            ),
            self.assertRaises(SystemExit),
        ):
            SCRIPT.main()


if __name__ == "__main__":
    main()
