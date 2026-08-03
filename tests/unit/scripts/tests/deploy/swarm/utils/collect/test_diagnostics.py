"""Contract of the swarm stack-diagnostics collector's output routing.

``scripts/tests/deploy/swarm/utils/collect/diagnostics.sh`` switches its stdout
per section with ``exec``, so a mistake there does not fail a job: it silently
sends a section into the wrong file, or loses the whole capture while the caller
swallows the error with ``|| true``. Pinned here: every section lands in its own
file, no section bleeds into another, the job log gets one line instead of the
whole dump, and an unwritable output directory degrades to stdout rather than
killing the collector.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

COLLECTOR = (
    PROJECT_ROOT
    / "scripts"
    / "tests"
    / "deploy"
    / "swarm"
    / "utils"
    / "collect"
    / "diagnostics.sh"
)
APP_ID = "web-app-gitea"
TOPICS = (
    "compose-tree",
    "images",
    "env-lengths",
    "nfs-exports",
    "nfs-boundary",
    "ganesha-threads",
    "controller-nfs",
    "volumes-mounts",
    "node-resolver",
    "node-disk",
)
RESOLVER_HEADING = "per-node name resolution state"


class TestSwarmDiagnosticsRouting(unittest.TestCase):
    def _run(self, tmp: Path, rescue: Path) -> subprocess.CompletedProcess:
        stub_bin = tmp / "bin"
        stub_bin.mkdir()
        docker = stub_bin / "docker"
        docker.write_text("#!/usr/bin/env bash\necho stub-docker-output\nexit 0\n")
        docker.chmod(0o755)

        env = dict(os.environ)
        env.update(
            APP_ID=APP_ID,
            INFINITO_RESCUE_DIAGNOSTICS_DIR=str(rescue),
            INFINITO_SWARM_NFS_EXPORT_BASE="/srv/nfs",
            INFINITO_SWARM_NFS_STATE_PATH="/srv/nfs/state",
            PATH=f"{stub_bin}:{env['PATH']}",
            BASH_ENV="",
        )
        return subprocess.run(
            ["bash", str(COLLECTOR)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_every_section_lands_in_its_own_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rescue = Path(tmp) / "rescue"
            self._run(Path(tmp), rescue)
            out = rescue / f"{APP_ID}-stack"
            for topic in TOPICS:
                self.assertTrue(
                    (out / f"{topic}.txt").is_file(), f"{topic}.txt was not written"
                )

    def test_a_section_does_not_bleed_into_another_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rescue = Path(tmp) / "rescue"
            self._run(Path(tmp), rescue)
            out = rescue / f"{APP_ID}-stack"
            carrying = [
                path.name
                for path in sorted(out.glob("*.txt"))
                if RESOLVER_HEADING in read_text(str(path))
            ]
            self.assertEqual(carrying, ["node-resolver.txt"])

    def test_the_job_log_gets_one_line_not_the_dump(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rescue = Path(tmp) / "rescue"
            proc = self._run(Path(tmp), rescue)
            self.assertEqual(len(proc.stdout.strip().splitlines()), 1)
            self.assertIn(str(rescue), proc.stdout)
            self.assertNotIn(RESOLVER_HEADING, proc.stdout)

    def test_an_unwritable_output_dir_degrades_to_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "blocker"
            blocker.write_text("not a directory\n")
            proc = self._run(Path(tmp), blocker / "rescue")
            self.assertIn("no writable output dir", proc.stdout)
            self.assertIn(RESOLVER_HEADING, proc.stdout)


if __name__ == "__main__":
    unittest.main()
