import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/sys-ctl-hlth-volumes/files/script.sh"

BOOTSTRAP = "/var/www/bootstrap"
VOL_A = "a" * 64
VOL_B = "b" * 64

CONTAINER_STUB = """#!/usr/bin/env bash
if [ "$1" = "volume" ] && [ "$2" = "ls" ]; then
\tif [[ "$*" == *"driver=local"* ]]; then
\t\texit 0
\tfi
\tprintf '%s\\n' $STUB_VOLUMES
\texit 0
fi
if [ "$1" = "ps" ]; then
\targs="$*"
\tvol="${args##*volume=}"
\tif [[ "$args" == *-aq* ]]; then
\t\teval "printf '%s\\n' \\$STUB_CONTAINERS_${vol}"
\telse
\t\teval "printf '%s\\n' \\$STUB_RUNNING_${vol}"
\tfi
\texit 0
fi
if [ "$1" = "inspect" ]; then
\tif [[ "$5" == *Mounts* ]]; then
\t\teval "printf '%s' \\"\\$STUB_MOUNT_$6\\""
\telse
\t\tprintf '/%s' "$6"
\tfi
\texit 0
fi
exit 0
"""


class TestHlthVolumesScript(unittest.TestCase):
    def run_script(self, *, volumes, containers, mounts, running=None, whitelist=""):
        """Run the health script against a stubbed container CLI.

        Args:
            volumes: volume names `container volume ls` reports.
            containers: volume name -> space separated container ids holding it.
            mounts: container id -> destination the volume is mounted at.
            running: volume name -> the subset of those ids still running; a
                volume absent here has no running container left.
            whitelist: value for the script's only positional argument.

        Returns:
            Tuple of the exit code and stdout.
        """
        running = running or {}
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            stub = bin_dir / "container"
            stub.write_text(CONTAINER_STUB)
            stub.chmod(0o755)
            env = dict(os.environ)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["STUB_VOLUMES"] = " ".join(volumes)
            for volume, ids in containers.items():
                env[f"STUB_CONTAINERS_{volume}"] = ids
                env[f"STUB_RUNNING_{volume}"] = running.get(volume, "")
            for container_id, destination in mounts.items():
                env[f"STUB_MOUNT_{container_id}"] = destination
            done = subprocess.run(
                ["bash", str(SCRIPT), whitelist],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            return done.returncode, done.stdout

    def test_bootstrap_volume_on_a_stopped_container_is_skipped(self):
        code, out = self.run_script(
            volumes=[VOL_A],
            containers={VOL_A: "reaped"},
            mounts={"reaped": BOOTSTRAP},
            running={},
        )
        self.assertEqual(code, 0)
        self.assertIn("is a bootstrap volume", out)

    def test_bootstrap_volume_held_by_two_containers_is_skipped(self):
        code, out = self.run_script(
            volumes=[VOL_A],
            containers={VOL_A: "reaped live"},
            mounts={"reaped": BOOTSTRAP, "live": BOOTSTRAP},
            running={VOL_A: "live"},
        )
        self.assertEqual(code, 0)
        self.assertIn("is a bootstrap volume", out)

    def test_volume_mounted_elsewhere_is_reported(self):
        code, out = self.run_script(
            volumes=[VOL_B],
            containers={VOL_B: "live"},
            mounts={"live": "/data"},
        )
        self.assertEqual(code, 1)
        self.assertIn("at mount path /data", out)

    def test_whitelisted_volume_is_skipped(self):
        code, out = self.run_script(
            volumes=[VOL_B],
            containers={VOL_B: "live"},
            mounts={"live": "/data"},
            whitelist=VOL_B,
        )
        self.assertEqual(code, 0)
        self.assertIn("is whitelisted", out)

    def test_unused_volume_is_reported(self):
        code, out = self.run_script(volumes=[VOL_B], containers={}, mounts={})
        self.assertEqual(code, 1)
        self.assertIn("is not used by any container", out)


if __name__ == "__main__":
    unittest.main()
