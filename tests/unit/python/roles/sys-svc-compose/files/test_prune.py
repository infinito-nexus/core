import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/sys-svc-compose/files/shell/prune.sh"

CONTAINER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${STUB_LOG}"
"""


class TestComposePrune(unittest.TestCase):
    def run_prune(self, *args):
        """Run prune.sh against a stubbed container CLI.

        Args:
            args: the arguments prune.sh receives.

        Returns:
            Tuple of the exit code and every container CLI call, one string each.
        """
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "container"
            stub.write_text(CONTAINER_STUB)
            stub.chmod(0o755)
            log = Path(tmp) / "calls"
            env = dict(os.environ)
            env["PATH"] = f"{tmp}{os.pathsep}{env['PATH']}"
            env["STUB_LOG"] = str(log)
            done = subprocess.run(
                ["bash", str(SCRIPT), *args],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            calls = log.read_text().splitlines() if log.exists() else []
        return done.returncode, calls

    def test_the_image_prune_spares_images_with_the_keep_label(self):
        rc, calls = self.run_prune("nexus.infinito.prune=keep")
        self.assertEqual(rc, 0)
        image_prunes = [call for call in calls if call.startswith("image prune")]
        self.assertEqual(
            image_prunes, ["image prune -af --filter label!=nexus.infinito.prune=keep"]
        )

    def test_a_missing_keep_label_stops_before_anything_is_pruned(self):
        rc, calls = self.run_prune()
        self.assertNotEqual(rc, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
