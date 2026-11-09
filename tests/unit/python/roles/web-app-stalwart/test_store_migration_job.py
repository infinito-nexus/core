from __future__ import annotations

import fcntl
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-stalwart"
MIGRATE_TASKS = ROLE / "tasks" / "store_guard" / "migrate.yml"
SCRIPT = ROLE / "files" / "shell" / "migrate_v016.sh"
VARS = ROLE / ROLE_FILE_VARS_MAIN

MIGRATION_TASK = "upgrade to final"
IMAGE = "stalwartlabs/stalwart-migrate:1.0.0"

STUB_CONTAINER = """#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
if [ "$1" = ps ] && [ -f "$PS_OUT" ]; then
  cat "$PS_OUT"
fi
"""


def _migration_task() -> dict:
    tasks = load_yaml_any(str(MIGRATE_TASKS), default_if_missing=[])
    return next(task for task in tasks if MIGRATION_TASK in task["name"])


def _seconds(value, variables: dict) -> int:
    reference = re.fullmatch(r"\{\{\s*(\w+)\s*\}\}", str(value).strip())
    if reference:
        value = variables[reference.group(1)]
    scaled = re.fullmatch(
        r"\{\{\s*lookup\('timeout',\s*(\d+)\)\s*\|\s*int\s*\}\}", str(value).strip()
    )
    return int(scaled.group(1)) if scaled else int(value)


def _is_polled_job(task: dict, variables: dict) -> bool:
    """Whether the task runs as an async job the play waits for within a budget.

    Args:
        task: the task as loaded from YAML.
        variables: the role's vars, to resolve the async and poll references.
    """
    if "async" not in task or "poll" not in task:
        return False
    budget = _seconds(task["async"], variables)
    poll = _seconds(task["poll"], variables)
    return 0 < poll < budget


class TestTheMigrationOutlivesItsSshConnection(unittest.TestCase):
    def setUp(self):
        self.variables = load_yaml_any(str(VARS), default_if_missing={})
        self.task = _migration_task()

    def test_the_migration_runs_as_a_polled_async_job(self):
        self.assertTrue(_is_polled_job(self.task, self.variables))

    def test_the_budget_is_bounded_and_scales_with_the_timeout_factor(self):
        self.assertRegex(
            self.variables["STALWART_MIGRATE_ASYNC_TIME"], r"lookup\('timeout',"
        )
        self.assertGreater(_seconds(self.task["async"], self.variables), 3600)

    def test_a_plain_command_is_not_a_polled_job(self):
        plain = {
            key: value
            for key, value in self.task.items()
            if key not in ("async", "poll")
        }
        self.assertFalse(_is_polled_job(plain, self.variables))

    def test_fire_and_forget_is_not_a_polled_job(self):
        self.assertFalse(_is_polled_job({**self.task, "poll": 0}, self.variables))


class TestASecondRunStopsAtOnce(unittest.TestCase):
    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workdir)
        self.script = self.workdir / "migrate.sh"
        shutil.copyfile(SCRIPT, self.script)
        values = {
            "IMAGE": IMAGE,
            "NETWORK": "postgres",
            "SOURCE_DIR": str(self.workdir / "source"),
            "TARGET_DIR": str(self.workdir / "target"),
            "STATE_DIR": str(self.workdir / "state"),
            "BACKUP_FILE": str(self.workdir / "backup" / "stalwart-v016.dump"),
            "PG_ADDRESS": "postgres",
            "PG_ADMIN": "postgres",
            "DB": "stalwart",
        }
        (self.workdir / "migrate.env").write_text(
            "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items())
        )
        bindir = self.workdir / "bin"
        bindir.mkdir()
        stub = bindir / "container"
        stub.write_text(STUB_CONTAINER)
        stub.chmod(0o755)
        self.calls = self.workdir / "calls.log"
        self.ps_out = self.workdir / "ps.out"
        self.env = {
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(self.calls),
            "PS_OUT": str(self.ps_out),
        }

    def _run(self, phase: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.script), phase],
            env=self.env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )

    def _hold_lock(self):
        handle = (self.workdir / "migrate.lock").open("w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _calls(self) -> list[str]:
        if not self.calls.exists():
            return []
        log = self.calls.read_text()  # nocheck: cache-read  tempdir stub log
        return log.splitlines()

    def test_a_free_lock_lets_the_phase_run(self):
        result = self._run("backup")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(call.startswith("exec ") for call in self._calls()))

    def test_a_held_lock_stops_the_phase_before_it_touches_anything(self):
        self._hold_lock()
        result = self._run("backup")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("another run holds", result.stderr)
        self.assertEqual([], self._calls())

    def test_a_held_lock_stops_the_whole_run(self):
        self._hold_lock()
        result = self._run("all")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("another run holds", result.stderr)
        self.assertEqual([], self._calls())

    def test_a_container_of_an_earlier_run_stops_the_phase(self):
        self.ps_out.write_text("4f2a9c1d0b7e\n")
        result = self._run("backup")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("still runs", result.stderr)
        self.assertFalse(any(call.startswith("exec ") for call in self._calls()))

    def test_status_reads_the_progress_while_a_run_holds_the_lock(self):
        self._hold_lock()
        result = self._run("status")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(call.startswith("run ") for call in self._calls()))


if __name__ == "__main__":
    unittest.main()
