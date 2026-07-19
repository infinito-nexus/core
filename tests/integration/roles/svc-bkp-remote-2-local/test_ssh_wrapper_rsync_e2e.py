"""End-to-end guard for the backup pull ssh forced-command wrapper.

A real rsync client is routed through the rendered
``roles/user-backup/templates/ssh-wrapper.sh.j2`` via a fake-ssh transport,
reproducing the DR-drill pull path (``--server --sender`` + ``--numeric-ids``).

Trip-wire this test exists for: the wrapper used to exact-match a fixed rsync
flag string, so an rsync version bump (3.4.x renegotiated the flag block) made
the match fall through to the reject echo, which polluted the rsync protocol
stream and killed every pull with ``protocol incompatibility (code 2)``. This
runs against the host's actual rsync so a future version drift fails here
instead of only in a swarm deploy.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Template

from utils.cache.files import read_text

from . import PROJECT_ROOT

WRAPPER_TEMPLATE = (
    PROJECT_ROOT / "roles" / "user-backup" / "templates" / "ssh-wrapper.sh.j2"
)
BACKUP_TYPE = "backup-docker-to-local"
VERSION = "20260101000000"


def _executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@unittest.skipUnless(
    shutil.which("rsync") and shutil.which("ssh") and shutil.which("sha256sum"),
    "rsync, ssh and sha256sum are required for the wrapper e2e test",
)
class TestSshWrapperRsyncE2E(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="ssh-wrapper-e2e-"))
        self.backups = self.work / "backups"
        self.mid = self.work / "machine-id"
        self.mid.write_text("integration-test-machine-id\n")
        self.hashed = subprocess.run(
            ["sha256sum", str(self.mid)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout[:64]

        self.version_dir = self.backups / self.hashed / BACKUP_TYPE / VERSION
        (self.version_dir / "data").mkdir(parents=True)
        (self.version_dir / "data" / "file1.txt").write_text("hello-backup")
        (self.version_dir / "data" / "file2.txt").write_text("second")

        self.wrapper = self.work / "wrapper.sh"
        rendered = Template(read_text(str(WRAPPER_TEMPLATE))).render(
            DIR_BACKUPS=str(self.backups),
            BACKUP_REPOSITORIES=[BACKUP_TYPE],
        )
        rendered = rendered.replace(
            "sha256sum /etc/machine-id", f"sha256sum {self.mid}"
        )
        self.wrapper.write_text(rendered)

        bindir = self.work / "bin"
        bindir.mkdir()
        self.sudo_shim = bindir / "sudo"
        self.sudo_shim.write_text('#!/bin/sh\nexec "$@"\n')
        _executable(self.sudo_shim)
        self.bindir = bindir

        self.fake_ssh = self.work / "fake-ssh"
        self.fake_ssh.write_text(
            "#!/bin/sh\n"
            "shift\n"
            f'export PATH="{bindir}:$PATH"\n'
            f'SSH_ORIGINAL_COMMAND="$*" exec sh "{self.wrapper}"\n'
        )
        _executable(self.fake_ssh)

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def _run_wrapper(self, original_command: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PATH"] = f"{self.bindir}:{env['PATH']}"
        env["SSH_ORIGINAL_COMMAND"] = original_command
        return subprocess.run(
            ["sh", str(self.wrapper)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_real_rsync_pull_through_wrapper(self) -> None:
        dest = self.work / "dest"
        dest.mkdir()
        result = subprocess.run(
            [
                "rsync",
                "-abP",
                "--numeric-ids",
                "--delete",
                "--delete-excluded",
                "--timeout=300",
                "-e",
                str(self.fake_ssh),
                "--rsync-path=sudo rsync",
                f"fakehost:{self.version_dir}/",
                f"{dest}/",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"rsync pull through wrapper failed (rsync {shutil.which('rsync')}):\n"
            f"{result.stdout}\n{result.stderr}",
        )
        f1 = dest / "data" / "file1.txt"
        f2 = dest / "data" / "file2.txt"
        self.assertEqual(f1.read_text(), "hello-backup")  # nocheck: cache-read
        self.assertEqual(f2.read_text(), "second")  # nocheck: cache-read

    def test_version_directory_listing(self) -> None:
        listing = self._run_wrapper(
            f"ls -d {self.backups}/{self.hashed}/{BACKUP_TYPE}/*"
        )
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn(VERSION, listing.stdout)

    def test_injection_attempts_are_rejected(self) -> None:
        pwned = self.work / "pwned"
        cases = [
            f"sudo rsync --server --sender -x ; touch {pwned} . {self.version_dir}/",
            f"sudo rsync --server --sender -x $(touch {pwned}) . {self.version_dir}/",
            f"sudo rsync --server --sender -x `touch {pwned}` . {self.version_dir}/",
            "sudo rsync --server --sender -x . /etc/",
        ]
        for cmd in cases:
            with self.subTest(command=cmd):
                result = self._run_wrapper(cmd)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("not supported", result.stdout + result.stderr)
                self.assertFalse(
                    pwned.exists(),
                    f"guard let a metacharacter execute: {cmd}",
                )


if __name__ == "__main__":
    unittest.main()
