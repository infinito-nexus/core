from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "web-app-stalwart" / "files" / "shell" / "migrate_v016.sh"
)
CONTAINER_STUB = r"""#!/bin/sh
printf '%s\n' "$*" >>"$STUB_LOG"
case "$*" in
  *" --help") echo "stalwart-migrate migrates a Stalwart v0.16 deployment to v1.0" ;;
  *"{{.Config.Image}}"*) echo "stalwartlabs/stalwart:v0.16.27" ;;
  *"{{.Image}}"*) echo "sha256:last" ;;
  "image inspect "*) echo "sha256:last" ;;
  *"{{range "*) echo "stalwart_net " ;;
  *"FROM pg_database"*) echo 0 ;;
  *'RENAME TO "stalwart"'*) : >"$STUB_SWAPPED" ;;
  *"SELECT layout"*) if [ -e "$STUB_SWAPPED" ]; then echo bytea; else echo bigint; fi ;;
  *" run --final "*) exit "$STUB_FINAL_RC" ;;
  *" report "*) if [ "$STUB_REPORT_RC" != 0 ]; then exit "$STUB_REPORT_RC"; fi; echo "row of $*" ;;
esac
"""


def run_final(
    final_rc: int, report_rc: int
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the final phase against a stubbed container CLI.

    Args:
        final_rc: exit code of `stalwart-migrate run --final`.
        report_rc: exit code of `stalwart-migrate report`.

    Returns:
        The finished script and the container CLI calls it made, in order.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "container"
        stub.write_text(CONTAINER_STUB)
        stub.chmod(0o755)
        stage = root / "migrate-v016"
        stage.mkdir()
        script = stage / "migrate.sh"
        shutil.copy(SCRIPT, script)
        values = {
            "IMAGE": "stalwartlabs/stalwart-migrate:1.0.4",
            "TARGET_VERSION": "v1.0.1",
            "NETWORK": "stalwart_net",
            "PG_ADMIN": "postgres",
            "PG_ADDRESS": "postgres",
            "DB": "stalwart",
            "DB_OWNER": "stalwart",
            "DB_V1": "stalwart_v1",
            "DB_V016": "stalwart_v016",
            "LAYOUT_SQL": "SELECT layout",
            "SOURCE_DIR": str(root / "etc"),
            "TARGET_DIR": str(stage / "target"),
            "STATE_DIR": str(stage / "state"),
            "BACKUP_FILE": str(stage / "backup" / "stalwart-v016.dump"),
            "MARKER": str(root / "store.layout"),
            "DEPLOYMENT_MODE": "compose",
            "STALWART_CONTAINER": "stalwart",
            "STACK_DIR": str(root),
            "COMPOSE_SERVICE": "stalwart",
            "STALWART_ADDRESS": "stalwart",
        }
        (stage / "migrate.env").write_text(
            "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items())
        )
        log = root / "container.log"
        log.touch()
        done = subprocess.run(
            ["bash", str(script), "final"],
            env={
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_LOG": str(log),
                "STUB_SWAPPED": str(root / "swapped"),
                "STUB_FINAL_RC": str(final_rc),
                "STUB_REPORT_RC": str(report_rc),
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = log.read_text().splitlines()  # nocheck: cache-read  stub call log
    return done, calls


def position(calls: list[str], fragment: str) -> int:
    return next(index for index, call in enumerate(calls) if fragment in call)


class TestAFailedFinalRunShowsWhyAndSwapsNothing(unittest.TestCase):
    def test_the_report_rows_follow_the_restart_of_0_16(self) -> None:
        done, calls = run_final(final_rc=1, report_rc=0)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        stop = calls.index("stop stalwart")
        final = position(calls, " run --final ")
        start = calls.index("start stalwart")
        errors = position(calls, "report --state /migrate/state --severity error")
        verify = position(calls, "report --state /migrate/state --severity verify")
        self.assertLess(stop, final)
        self.assertLess(final, start)
        self.assertLess(start, errors)
        self.assertLess(errors, verify)
        self.assertIn(" --verify-full ", calls[final])
        self.assertFalse([call for call in calls if "RENAME" in call], calls)
        self.assertIn("--severity verify", done.stderr)
        self.assertIn("the final run failed and nothing was swapped", done.stderr)

    def test_a_failing_report_still_ends_in_the_final_error(self) -> None:
        done, calls = run_final(final_rc=1, report_rc=3)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("start stalwart", calls)
        self.assertIn("could not list the rows", done.stderr)
        self.assertIn("the final run failed and nothing was swapped", done.stderr)

    def test_a_passing_final_run_swaps_without_a_report(self) -> None:
        done, calls = run_final(final_rc=0, report_rc=0)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse([call for call in calls if " report " in call], calls)
        self.assertNotIn("start stalwart", calls)
        self.assertEqual(len([call for call in calls if "RENAME" in call]), 2, calls)
        self.assertIn("final: stalwart holds the 1.x store", done.stdout)


if __name__ == "__main__":
    unittest.main()
