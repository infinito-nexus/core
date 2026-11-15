from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
import unittest
import unittest.mock as mock

from utils import PROJECT_ROOT

PROBE_DIR = PROJECT_ROOT / "roles/web-svc-seaweedfs/files/test"
sys.path.insert(0, str(PROBE_DIR))

spec = importlib.util.spec_from_file_location(
    "seaweedfs_engine_probe", PROBE_DIR / "probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

ADMIN = ("ADMINKEY", "adminsecret")
BUCKET = "matrix"
KEY = "infinito-engine-check/0123-restart-race"
WINDOW = 0.05
TIMING = {"interval": 0.005, "settle": 0.02, "timeout": 0.3}
DOWN = "down"
LOADING = "loading"
LOADED = "loaded"


class FakeEngine:
    def __init__(self, *, served_while_loading: bool = False) -> None:
        self.state = LOADED
        self.served_while_loading = served_while_loading
        self.writes: list[str] = []

    def request(
        self, method, path, *, query=None, payload=b"", access_key="", secret_key=""
    ):
        state = self.state
        if state == DOWN:
            return 0, b"[Errno 111] Connection refused", {}
        if access_key:
            return (200 if state == LOADED else 503), b"", {}
        self.writes.append(path)
        if state == LOADING and self.served_while_loading:
            return 200, b"", {}
        return 403, b"<Error><Code>AccessDenied</Code></Error>", {}


def restart(engine: FakeEngine, *, goes_down: bool = True, loads: bool = True):
    def run() -> list[str]:
        if goes_down:
            engine.state = DOWN
            time.sleep(WINDOW)
            engine.state = LOADING
            time.sleep(WINDOW)
        if loads:
            engine.state = LOADED
        return []

    return run


def race(engine: FakeEngine, restarter, **timing) -> list[str]:
    return probe.check_restart_serves_no_anonymous_write(
        engine, ADMIN, BUCKET, KEY, restarter, **{**TIMING, **timing}
    )


class TestRestartRace(unittest.TestCase):
    def test_no_anonymous_write_is_served_across_a_restart(self) -> None:
        engine = FakeEngine()
        self.assertEqual(race(engine, restart(engine)), [])
        self.assertEqual(set(engine.writes), {f"/{BUCKET}/{KEY}"})

    def test_negative_control_a_write_served_before_the_identities_load_is_caught(
        self,
    ) -> None:
        engine = FakeEngine(served_while_loading=True)
        (failure,) = race(engine, restart(engine))
        self.assertIn(f"/{BUCKET}/{KEY} answered 200", failure)

    def test_negative_control_a_loop_that_never_meets_the_restart_is_caught(
        self,
    ) -> None:
        engine = FakeEngine()
        (failure,) = race(engine, restart(engine, goes_down=False))
        self.assertIn("never spanned the restart", failure)

    def test_an_engine_that_never_loads_its_identities_fails(self) -> None:
        engine = FakeEngine()
        failures = race(engine, restart(engine, loads=False), timeout=0.05)
        self.assertTrue(any("loaded no identities" in failure for failure in failures))

    def test_a_failed_restart_is_reported(self) -> None:
        engine = FakeEngine()
        failures = race(engine, lambda: ["F: container restart x failed: gone"])
        self.assertIn("F: container restart x failed: gone", failures)
        self.assertTrue(
            any("never spanned the restart" in failure for failure in failures)
        )


def completed(
    stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class TestRestartContainer(unittest.TestCase):
    def _restart(self, before: str, after: str, returncode: int = 0) -> list[str]:
        answers = [
            completed(before),
            completed(returncode=returncode),
            completed(after),
        ]
        with mock.patch.object(probe.subprocess, "run", side_effect=answers) as run:
            failures = probe.restart_container("seaweedfs")
        self.assertEqual(
            run.call_args_list[1].args[0], ["container", "restart", "seaweedfs"]
        )
        return failures

    def test_a_new_start_time_proves_the_restart(self) -> None:
        self.assertEqual(
            self._restart("2026-11-14T10:00:00Z", "2026-11-14T10:05:00Z"), []
        )

    def test_negative_control_an_unchanged_start_time_is_caught(self) -> None:
        (failure,) = self._restart("2026-11-14T10:00:00Z", "2026-11-14T10:00:00Z")
        self.assertIn("never restarted", failure)

    def test_a_failed_restart_command_is_reported(self) -> None:
        (failure,) = self._restart("2026-11-14T10:00:00Z", "", returncode=1)
        self.assertIn("container restart seaweedfs failed", failure)


if __name__ == "__main__":
    unittest.main()
