from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock

from utils.storage.nfs import fstype

from .test_script import MAIN_SCAN, NO_SUPPRESSIONS, SCRIPT, _config

MOUNTINFO_FIELDS = (
    ("22", "1", "0:21", "/", "/", "rw", "shared:1", "-", "overlay", "overlay", "rw"),
    ("25", "22", "0:5", "/", "/proc", "rw", "shared:12", "-", "proc", "proc", "rw"),
    ("30", "22", "0:31", "/", "/mnt/docker-fs", "rw", "-", "zfs", "pool/node", "rw"),
    (
        "310",
        "22",
        "0:60",
        "/",
        "/var/lib/infinito",
        "rw,relatime",
        "shared:150",
        "-",
        "nfs4",
        "10.100.1.11:/srv/nfs/infinito-state",
        "rw,vers=4.2,soft,timeo=50,retrans=3",
    ),
    (
        "311",
        "310",
        "0:31",
        "/var/lib/infinito-backup",
        "/var/lib/infinito/backup",
        "rw",
        "shared:1",
        "-",
        "zfs",
        "pool/node",
        "rw",
    ),
    (
        "312",
        "30",
        "0:61",
        "/",
        "/mnt/docker-fs/docker/volumes/hermes_redis/_data",
        "rw",
        "-",
        "nfs4",
        "10.100.1.11:/srv/nfs/infinito-state/hermes_redis",
        "rw",
    ),
    (
        "313",
        "22",
        "0:62",
        "/",
        "/srv/team\\040share",
        "rw",
        "shared:160",
        "master:3",
        "-",
        "cifs",
        "//files/team",
        "rw",
    ),
    (
        "314",
        "22",
        "0:63",
        "/",
        "/home/admin/remote",
        "rw,nosuid",
        "-",
        "fuse.sshfs",
        "admin@backup:",
        "rw",
    ),
    ("315", "22", "0:64", "/", "/run/user/1000", "rw", "-", "tmpfs", "tmpfs", "rw"),
    ("316", "22", "0:65", "/", "/srv/a,b", "rw", "-", "cifs", "//files/ab", "rw"),
)
SWARM_NODE_MOUNTINFO = "\n".join(" ".join(fields) for fields in MOUNTINFO_FIELDS)
REMOTE = [
    "/home/admin/remote",
    "/mnt/docker-fs/docker/volumes/hermes_redis/_data",
    "/srv/a,b",
    "/srv/team share",
    "/var/lib/infinito",
]
NOT_UTF8_MOUNTINFO = b"1 0 0:20 / /srv/caf\xe9 rw - nfs4 server:/cafe rw\n"
GLOB_MOUNTS = ("/srv/q{a,b}]?*\\w", "/srv/x[y", "/var/lib/docker")


def _values(argv, flag):
    return [argv[index + 1] for index, arg in enumerate(argv) if arg == flag]


def _literal(pattern):
    """
    Args:
        pattern: a doublestar pattern as Trivy, Syft and Grype match it.

    Returns:
        The one path the pattern matches, or None while it holds an unescaped
        glob character or ends in a lone backslash.
    """
    chars = iter(pattern)
    path = []
    for char in chars:
        if char == "\\":
            escaped = next(chars, None)
            if escaped is None:
                return None
            path.append(escaped)
        elif char in "*?[]{}":
            return None
        else:
            path.append(char)
    return "".join(path)


def _layout(*excludes):
    return SCRIPT.Layout(
        runtime=("container", "run"),
        databases=Path("/var/cache/v/db"),
        sbom=Path("/var/cache/v/sbom"),
        work=Path("/var/cache/v/run"),
        excludes=excludes,
    )


def _main(mountinfo, targets):
    """
    Args:
        mountinfo: the bytes of the host's mountinfo, or None for no file.
        targets: the scan targets.

    Returns:
        ``(output, layouts)``: what the check printed and the layout of every
        scan it started.
    """
    layouts = []

    def scan(targets, config, images, layout, runner):
        layouts.append(layout)
        return [], []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in ("report", "log"):
            (root / name).mkdir()
        if mountinfo is not None:
            (root / "mountinfo").write_bytes(mountinfo)
        argv = [
            "--scan",
            json.dumps({**MAIN_SCAN, "targets": targets}),
            "--hardened",
            "{}",
            "--images",
            "{}",
            "--suppressions",
            json.dumps(NO_SUPPRESSIONS),
            "--cache-dir",
            str(root / "cache"),
            "--database-dir",
            str(root / "cache" / "db"),
            "--host-excludes",
            '["/proc"]',
            "--environment",
            "production",
            "--host",
            "node",
            "--report-dir",
            str(root / "report"),
            "--log-dir",
            str(root / "log"),
        ]
        with (
            mock.patch.object(SCRIPT, "MOUNTINFO", root / "mountinfo"),
            mock.patch.object(SCRIPT, "running_containers", return_value=[]),
            mock.patch.object(SCRIPT, "check", return_value=([], [])),
            mock.patch.object(SCRIPT, "docker_root", return_value="/var/lib/docker"),
            mock.patch.object(SCRIPT, "scan", side_effect=scan),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            SCRIPT.main(argv)
    return out.getvalue(), layouts


def _engine_skips(layout):
    host = SCRIPT.host_target("node")
    trivy = SCRIPT.trivy_step(layout, "trivy:1", host, _config(), [])
    syft = SCRIPT.sbom_step(layout, "syft:1", host)
    grype = SCRIPT.grype_step(layout, "grype:1", host, _config(engines=["grype"]))
    return {
        "trivy": [
            _literal(pattern)
            for value in _values(trivy.argv, "--skip-dirs")
            for pattern in next(csv.reader([value]))
        ],
        "syft": [_literal(pattern) for pattern in _values(syft.argv, "--exclude")],
        "grype": [_literal(pattern) for pattern in _values(grype.argv, "--exclude")],
    }


def _expected_skips(point):
    return {
        "trivy": f"{SCRIPT.HOST_ROOT}{point}",
        "syft": f"./{point.strip('/')}",
        "grype": f"./{point.strip('/')}",
    }


class TestNetworkMounts(TestCase):
    def test_every_network_filesystem_is_found_with_its_escaped_path(self):
        self.assertEqual(SCRIPT.network_mounts(SWARM_NODE_MOUNTINFO), REMOTE)

    def test_local_filesystems_and_binds_of_local_trees_are_kept(self):
        found = SCRIPT.network_mounts(SWARM_NODE_MOUNTINFO)
        for point in ("/", "/proc", "/mnt/docker-fs", "/var/lib/infinito/backup"):
            with self.subTest(point=point):
                self.assertNotIn(point, found)

    def test_a_network_root_is_still_scanned(self):
        self.assertEqual(
            SCRIPT.network_mounts("1 0 0:20 / / rw - nfs4 server:/root rw"), []
        )

    def test_the_shared_state_mount_of_every_nfs_version_is_found(self):
        for version in (3, 4):
            with self.subTest(version=version):
                self.assertIn(fstype(version), SCRIPT.NETWORK_FSTYPES)


class TestSkipPatterns(TestCase):
    def test_a_mount_point_with_a_comma_stays_one_skip_dir(self):
        self.assertEqual(
            _engine_skips(_layout("/srv/a,b"))["trivy"],
            [f"{SCRIPT.HOST_ROOT}/srv/a,b"],
        )

    def test_a_mount_point_with_glob_characters_matches_only_itself(self):
        skips = _engine_skips(_layout(*GLOB_MOUNTS))
        for engine in ("trivy", "syft", "grype"):
            with self.subTest(engine=engine):
                self.assertEqual(
                    skips[engine],
                    [_expected_skips(point)[engine] for point in GLOB_MOUNTS],
                )


class TestHostScanSkipsNetworkMounts(TestCase):
    def test_every_engine_skips_each_network_mount_and_the_check_reports_it(self):
        output, layouts = _main(SWARM_NODE_MOUNTINFO.encode(), ["host"])
        skips = _engine_skips(layouts[0])
        for point in REMOTE:
            with self.subTest(point=point):
                self.assertIn(
                    f"ℹ️ host scan skips the network or automounted filesystem at {point}",
                    output.splitlines(),
                )
                for engine, path in _expected_skips(point).items():
                    self.assertIn(path, skips[engine], engine)
        for engine, path in _expected_skips("/mnt/docker-fs").items():
            self.assertNotIn(path, skips[engine], engine)

    def test_a_mount_point_that_is_not_utf8_is_skipped_and_printed_escaped(self):
        output, layouts = _main(NOT_UTF8_MOUNTINFO, ["host"])
        point = os.fsdecode(b"/srv/caf\xe9")
        skips = _engine_skips(layouts[0])
        for engine, path in _expected_skips(point).items():
            self.assertIn(path, skips[engine], engine)
        self.assertIn(
            "ℹ️ host scan skips the network or automounted filesystem at /srv/caf\\xe9",
            output.splitlines(),
        )
        output.encode("utf-8")

    def test_a_mount_point_with_a_newline_prints_as_one_escaped_line(self):
        output, _layouts = _main(
            b"1 0 0:20 / /srv/a\\012forged rw - nfs4 server:/a rw\n", ["host"]
        )
        lines = output.splitlines()
        self.assertIn(
            "ℹ️ host scan skips the network or automounted filesystem at "
            "/srv/a\\nforged",
            lines,
        )
        self.assertNotIn("forged", [line.strip() for line in lines])

    def test_a_scan_without_the_host_reads_and_reports_no_mount(self):
        output, _layouts = _main(None, ["container"])
        self.assertNotIn("host scan skips", output)


if __name__ == "__main__":
    main()
