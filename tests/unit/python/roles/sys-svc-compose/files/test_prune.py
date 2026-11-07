import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/sys-svc-compose/files/shell/prune.sh"

CONTAINER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_CALLS"
if [ "$1" = "info" ]; then
\t[ -n "$STUB_ROOT" ] || exit 1
\tprintf '%s\\n' "$STUB_ROOT"
fi
exit 0
"""

DF_STUB = """#!/usr/bin/env bash
[ -n "$STUB_FREE_MIB" ] || exit 1
printf 'Avail\\n%sM\\n' "$STUB_FREE_MIB"
"""


class TestPruneScript(unittest.TestCase):
    def run_script(self, *, free_mib, floor_mib="30720", root="/var/lib/docker"):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            for name, body in (("container", CONTAINER_STUB), ("df", DF_STUB)):
                stub = bin_dir / name
                stub.write_text(body)
                stub.chmod(0o755)
            calls = Path(tmp) / "calls"
            calls.touch()
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "STUB_CALLS": str(calls),
                "STUB_ROOT": root,
                "STUB_FREE_MIB": free_mib,
            }
            if floor_mib is None:
                env.pop("PRUNE_FREE_FLOOR_MIB", None)
            else:
                env["PRUNE_FREE_FLOOR_MIB"] = floor_mib
            proc = subprocess.run(
                ["bash", str(SCRIPT)], env=env, capture_output=True, text=True
            )
            return proc, calls.read_text().splitlines()  # nocheck: cache-read the stub writes this tempdir log during the run

    def prunes(self, calls):
        return [call for call in calls if call.endswith(("prune -f", "prune -af"))]

    def test_free_at_the_floor_skips_every_prune(self):
        proc, calls = self.run_script(free_mib="30720")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("prune skipped", proc.stdout)
        self.assertEqual(self.prunes(calls), [])

    def test_free_below_the_floor_prunes(self):
        proc, calls = self.run_script(free_mib="30719")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("prune skipped", proc.stdout)
        self.assertEqual(
            self.prunes(calls),
            [
                "container prune -f",
                "image prune -af",
                "volume prune -f",
                "buildx prune -af",
                "builder prune -af",
            ],
        )

    def test_unreadable_data_root_prunes(self):
        proc, calls = self.run_script(free_mib="999999", root="")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.prunes(calls)), 5)

    def test_unmeasured_free_space_prunes(self):
        proc, calls = self.run_script(free_mib="")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.prunes(calls)), 5)

    def test_missing_floor_fails_before_any_prune(self):
        proc, calls = self.run_script(free_mib="999999", floor_mib=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("PRUNE_FREE_FLOOR_MIB", proc.stderr)
        self.assertEqual(self.prunes(calls), [])


if __name__ == "__main__":
    unittest.main()
