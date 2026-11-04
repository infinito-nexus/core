"""Budget-kill drills for the rescue window of the compose trap."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

DEPLOY = PROJECT_ROOT / "scripts" / "tests" / "deploy"
HELPER = DEPLOY / "utils" / "rescue" / "window.sh"
INDEX = DEPLOY / "utils" / "rescue" / "index.sh"
DEDICATED = DEPLOY / "ci" / "dedicated.sh"
COLLECTOR = PROJECT_ROOT / "utils" / "diagnostics" / "container.py"
DISTRO_PREFIX = "INFINITO_CI_DISTRO_"  # nocheck: prefix the drills strip, not a key
GRACE = 8
KILL_BUDGET = 3
SKIPPED = b"[skipped: past RESCUE_DEADLINE]\n"

WINDOW = """\
set -euo pipefail
. "$1"
now="$(date +%s)"
if [ -n "$2" ]; then
	export INFINITO_CI_DISTRO_DEADLINE_EPOCH="$((now + $2))"
	export INFINITO_CI_DISTRO_KILL_EPOCH="$((now + $3))"
fi
rescue_window "$4"
printf '%s %s %s\\n' "${now}" "${rescue_secs}" "${rescue_until:--}"
"""

DRIVER = """\
#!/usr/bin/env bash
set -euo pipefail
now="$(date +%s)"
deadline="$((now + BUDGET))"
if [ "${EPOCHS}" = true ]; then
	export INFINITO_CI_DISTRO_DEADLINE_EPOCH="${deadline}"
	export INFINITO_CI_DISTRO_KILL_EPOCH="$((deadline + GRACE))"
fi
echo "kill_epoch=$((deadline + GRACE))"
mkfifo "${SANDBOX}/armed"
set -m
bash "${SANDBOX}/stand-in.sh" "$@" &
deploy="$!"
set +m
read -r _ <"${SANDBOX}/armed"
left="$((deadline - $(date +%s)))"
sleep "$((left > 0 ? left : 0))" &
clock="$!"
status=0
wait -n -p first "${deploy}" "${clock}" || status="$?"
if [ "${first}" = "${clock}" ]; then
	kill -TERM -- "-${deploy}"
	sleep "${GRACE}" &
	grace="$!"
	wait -n -p first "${deploy}" "${grace}" || true
	if [ "${first}" = "${grace}" ]; then
		kill -KILL -- "-${deploy}"
		wait "${deploy}" || true
		status=137
	else
		kill "${grace}"
		status=124
	fi
else
	kill "${clock}"
fi
exit "${status}"
"""

STAND_IN = """\
#!/usr/bin/env bash
set -euo pipefail
. "${HELPER}"
cleanup() {
	local rescue_secs rescue_until
	rescue_window 1500
	INFINITO_RESCUE_DIAGNOSTICS_DIR="${SANDBOX}/in-container" \\
		INFINITO_DNS53_SAMPLER_LOG="${SANDBOX}/dns53.log" \\
		RESCUE_DEADLINE="${rescue_until}" \\
		PATH="${SANDBOX}/bin" \\
		"${TIMEOUT_BIN}" --foreground "${rescue_secs}" "${PYTHON_BIN}" "${COLLECTOR}" app drill >/dev/null 2>&1 || true
	mkdir -p "${SANDBOX}/host"
	tar -C "${SANDBOX}/in-container" -cf - . 2>/dev/null | tar -C "${SANDBOX}/host" -xf - 2>/dev/null || true
	bash "${INDEX}" "${SANDBOX}/host"
	date +%s >"${SANDBOX}/rescued"
}
trap cleanup EXIT
echo armed >"${SANDBOX}/armed"
"$@"
"""

STUB_JOURNAL = """\
#!/bin/sh
echo "RESCUE_DEADLINE=[${RESCUE_DEADLINE}]"
exec @SLEEP@ "${JOURNAL_SECONDS}"
"""


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(DISTRO_PREFIX)}
    env.update(BASH_ENV="", **extra)
    return env


class RescueWindowTests(unittest.TestCase):
    def _window(self, deadline: str, kill: str, nominal: int) -> tuple[int, int, str]:
        proc = subprocess.run(
            ["bash", "-c", WINDOW, "_", str(HELPER), deadline, kill, str(nominal)],
            env=_env(),
            capture_output=True,
            text=True,
            check=True,
        )
        now, secs, until = proc.stdout.splitlines()[-1].split()
        return int(now), int(secs), until

    def test_outside_distros_sh_a_step_keeps_its_nominal_time(self) -> None:
        _now, secs, until = self._window("", "", 1500)
        self.assertEqual((secs, until), (1500, "-"))

    def test_before_the_deadline_a_step_keeps_its_nominal_time(self) -> None:
        _now, secs, until = self._window("30", "90", 900)
        self.assertEqual((secs, until), (900, "-"))

    def test_past_the_deadline_a_step_gets_half_the_grace_left(self) -> None:
        now, secs, until = self._window("-1", "59", 1500)
        self.assertIn(secs, (29, 30))
        self.assertLessEqual(abs(int(until) - (now + secs)), 1)

    def test_a_kill_already_due_still_leaves_a_timeout_that_fires(self) -> None:
        _now, secs, until = self._window("-10", "-1", 1500)
        self.assertEqual(secs, 1)
        self.assertNotEqual(until, "-")


class DedicatedWiringTests(unittest.TestCase):
    def test_every_capture_runs_inside_the_window(self) -> None:
        text = read_text(str(DEDICATED))
        self.assertIn("utils/rescue/window.sh", text)
        self.assertIn("rescue_window 1500", text)
        self.assertIn("rescue_window 900", text)
        commands = text.replace("\\\n", " ").replace('"', "").splitlines()
        captures = [c for c in commands if "utils/diagnostics/container.py" in c]
        self.assertEqual(len(captures), 2, captures)
        for capture in captures:
            self.assertIn("timeout --foreground ${rescue_secs}", capture)
            self.assertIn("RESCUE_DEADLINE=${rescue_until}", capture)


class BudgetKillDrillTests(unittest.TestCase):
    def _drill(
        self, *deploy: str, budget: int, journal_seconds: str, epochs: bool
    ) -> tuple[subprocess.CompletedProcess, int, int | None, dict[str, bytes]]:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            (sandbox / "bin").mkdir()
            journal = sandbox / "bin" / "journalctl"
            journal.write_text(STUB_JOURNAL.replace("@SLEEP@", shutil.which("sleep")))
            journal.chmod(0o755)
            (sandbox / "stand-in.sh").write_text(STAND_IN)
            (sandbox / "driver.sh").write_text(DRIVER)
            proc = subprocess.run(
                ["bash", str(sandbox / "driver.sh"), *deploy],
                env=_env(
                    SANDBOX=str(sandbox),
                    HELPER=str(HELPER),
                    INDEX=str(INDEX),
                    COLLECTOR=str(COLLECTOR),
                    PYTHON_BIN=sys.executable,
                    TIMEOUT_BIN=shutil.which("timeout"),
                    BUDGET=str(budget),
                    GRACE=str(GRACE),
                    EPOCHS="true" if epochs else "false",
                    JOURNAL_SECONDS=journal_seconds,
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            kill_epoch = int(proc.stdout.split("kill_epoch=", 1)[1].split()[0])
            marker = sandbox / "rescued"
            rescued = (
                int(marker.read_text())  # nocheck: cache-read - tempdir fixture
                if marker.is_file()
                else None
            )
            files = {
                path.name: path.read_bytes()  # nocheck: cache-read - tempdir fixture
                for path in (sandbox / "host").glob("app-*/*")
                if path.is_file()
            }
            return proc, kill_epoch, rescued, files

    def test_a_budget_kill_copies_a_partial_snapshot_out_inside_the_grace(self) -> None:
        proc, kill_epoch, rescued, files = self._drill(
            "sleep", "1000", budget=KILL_BUDGET, journal_seconds="30", epochs=True
        )
        self.assertEqual(proc.returncode, 124, proc.stdout)
        self.assertIn("Budget kill:", proc.stdout)
        self.assertIsNotNone(rescued, proc.stdout)
        self.assertLess(rescued, kill_epoch)
        self.assertIn(b"application_id: app", files["meta.txt"])
        self.assertIn(b"timed out", files["journal.txt"])
        self.assertEqual(files["journal-errors.txt"], SKIPPED)
        self.assertIn("Rescue diagnostics:", proc.stdout)

    def test_without_the_window_the_kill_lands_before_the_copy(self) -> None:
        proc, _kill_epoch, rescued, files = self._drill(
            "sleep", "1000", budget=KILL_BUDGET, journal_seconds="30", epochs=False
        )
        self.assertEqual(proc.returncode, 137, proc.stdout)
        self.assertIsNone(rescued)
        self.assertEqual(files, {})

    def test_a_failure_before_the_deadline_keeps_the_unbounded_capture(self) -> None:
        proc, _kill_epoch, rescued, files = self._drill(
            "sh", "-c", "exit 3", budget=60, journal_seconds="0.2", epochs=True
        )
        self.assertEqual(proc.returncode, 3, proc.stdout)
        self.assertNotIn("Budget kill:", proc.stdout)
        self.assertIsNotNone(rescued)
        self.assertEqual(files["journal.txt"], b"RESCUE_DEADLINE=[]\n")
        self.assertNotIn(SKIPPED, files.values())


if __name__ == "__main__":
    unittest.main()
