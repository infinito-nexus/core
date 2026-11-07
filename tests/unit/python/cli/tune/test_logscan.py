"""Unit test: ``python -m cli.tune.logscan`` reads a fixture deploy log and
reports the cost per task, a per-item loop by its count and the retry waits
per retried task. ``profile_tasks`` prints a task's duration on the timestamp
line after the NEXT task's header, so the fixture writes it there."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from cli.tune.logscan import main, retries


def _timestamp(seconds: float) -> str:
    stamp = f"Freitag 06 November 2026  03:00:00 +0000 (0:00:{seconds:06.3f})   0:01:00.000 ***\n"
    return stamp + stamp


def deploy_log() -> str:
    """Return a deploy log: a 30 s realm import, a user loop of six 2 s
    items, a marker wait retried three times, and a closing task."""
    tasks = [("web-app-keycloak : Import the realm", 30.0)]
    tasks += [("svc-db-postgres : Create the role user", 2.0)] * 6
    tasks += [("web-app-gitea : Wait for the marker", 1.5)]
    text = ""
    previous = 0.0
    for label, seconds in tasks:
        text += f"TASK [{label}] {'*' * 40}\n"
        text += _timestamp(previous)
        text += "ok: [localhost]\n"
        previous = seconds
    text += "".join(
        f"FAILED - RETRYING: [localhost]: Wait for the marker ({left} retries left).\n"
        for left in (59, 58, 57)
    )
    text += f"TASK [web-app-gitea : Report] {'*' * 40}\n" + _timestamp(previous)
    return text


def report(log: str) -> str:
    """Return what ``python -m cli.tune.logscan <log>`` prints for ``log``."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "deploy.log"
        path.write_text(log, encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([str(path)])
    if code != 0:
        raise AssertionError(code)
    return out.getvalue()


class TestLogscanReport(unittest.TestCase):
    def test_reports_the_cost_per_task_slowest_first(self) -> None:
        lines = report(deploy_log()).splitlines()
        self.assertIn("30.0s  x1    web-app-keycloak : Import the realm", lines[1])

    def test_reports_a_per_item_loop_by_its_count(self) -> None:
        text = report(deploy_log())
        self.assertIn(
            "12.0s  x6    svc-db-postgres : Create the role user  <- per-item loop",
            text,
        )

    def test_reports_the_retry_waits_per_task(self) -> None:
        text = report(deploy_log())
        self.assertIn("# retries (a wait that hides a failure)", text)
        self.assertIn("  3x Wait for the marker", text)

    def test_retries_are_counted_per_task_not_per_host(self) -> None:
        log = (
            "FAILED - RETRYING: [localhost]: Wait for A (3 retries left).\n"
            "FAILED - RETRYING: [localhost]: Wait for B (3 retries left).\n"
        )
        self.assertEqual(retries(log), {"Wait for A": 1, "Wait for B": 1})

    def test_a_log_without_loops_or_retries_reports_neither(self) -> None:
        log = (
            f"TASK [a : one] {'*' * 10}\n{_timestamp(0.0)}"
            f"TASK [a : two] {'*' * 10}\n{_timestamp(3.0)}"
        )
        text = report(log)
        self.assertNotIn("per-item loop", text)
        self.assertNotIn("# retries", text)


if __name__ == "__main__":
    unittest.main()
