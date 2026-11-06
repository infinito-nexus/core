from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles" / "sys-ctl-cln-apps" / "files" / "shell" / "script.sh"

FAKE_CONTAINER = r"""#!/bin/sh
name=""
for arg in "$@"; do
  case "$arg" in
  name=*) name=$(printf '%s' "$arg" | sed -e 's|^name=^/?||' -e 's|\$$||') ;;
  esac
done
for running in ${FAKE_RUNNING}; do
  if [ "$running" = "$name" ]; then echo "id-$name"; fi
done
"""

FAKE_RESOLVER = """#!/bin/sh
[ -n "$1" ] && [ -n "$2" ] || exit 64
case "$2" in
local) echo "cid-$1" ;;
worker) exit 64 ;;
down) exit 65 ;;
remote) exit 66 ;;
*) exit 2 ;;
esac
"""

GARBAGE_COLLECTOR_SCRIPT = """#!/bin/sh
printf '%s %s\\n' "$1" "$GARBAGE_COLLECTOR_ADDRESS" >"$MARKER_DIR/{app}"
printf '%s\\n' "$GARBAGE_COLLECTOR_APP_TIMEOUT" >"$MARKER_DIR/{app}.timeout"
{body}
"""


def _write(path: Path, body: str, mode: int = 0o644) -> None:
    path.write_text(body)
    path.chmod(mode)


class DispatcherCase:
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.bin = root / "bin"
        self.manifest = root / "garbage-collector"
        self.markers = root / "markers"
        for directory in (self.bin, self.manifest, self.markers):
            directory.mkdir()
        _write(self.bin / "container", FAKE_CONTAINER, 0o755)
        _write(self.bin / "resolver", FAKE_RESOLVER, 0o755)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def app(
        self,
        name: str,
        *,
        container: str,
        mode: str = "compose",
        body: str = "exit 0",
        stack: str | None = None,
    ) -> None:
        entry = self.manifest / name
        entry.mkdir()
        _write(
            entry / "garbage_collector.sh",
            GARBAGE_COLLECTOR_SCRIPT.format(app=name, body=body),
            0o755,
        )
        stack = name if stack is None else stack
        _write(
            entry / "garbage_collector.env",
            f"DEPLOYMENT_MODE={mode}\nGARBAGE_COLLECTOR_CONTAINER={container}\nGARBAGE_COLLECTOR_STACK={stack}\nGARBAGE_COLLECTOR_SERVICE_KEY={container}\n",
        )

    def marker(self, name: str) -> str | None:
        path = self.markers / name
        if not path.is_file():
            return None
        return path.read_text().strip()  # nocheck: cache-read  written by the run

    def run_dispatcher(
        self, mode: str, timeout: str = "30"
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["/bin/bash", str(SCRIPT), mode],
            env={
                "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "GARBAGE_COLLECTOR_MANIFEST_DIR": str(self.manifest),
                "GARBAGE_COLLECTOR_APP_TIMEOUT": timeout,
                "BIN_RESOLVE_CONTAINER_ID": str(self.bin / "resolver"),
                "FAKE_RUNNING": "pass-c fail-c",
                "MARKER_DIR": str(self.markers),
            },
            capture_output=True,
            text=True,
            check=False,
        )


class TestDispatcher(DispatcherCase, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app("a-pass", container="pass-c")
        self.app("b-fail", container="fail-c", body="exit 3")
        self.app("c-skip", container="skip-c")

    def test_a_failing_app_does_not_stop_the_ones_after_it(self) -> None:
        self.app("d-after", container="pass-c")
        self.run_dispatcher("routine")
        self.assertEqual(self.marker("d-after"), "routine pass-c")

    def test_the_failing_app_is_named(self) -> None:
        done = self.run_dispatcher("routine")
        self.assertIn("garbage collector failed for: b-fail", done.stderr)

    def test_one_failure_fails_the_run(self) -> None:
        self.assertEqual(self.run_dispatcher("routine").returncode, 1)

    def test_an_app_without_a_running_container_is_skipped_with_a_warning(
        self,
    ) -> None:
        done = self.run_dispatcher("routine")
        self.assertIsNone(self.marker("c-skip"))
        self.assertIn("c-skip: warning: skipped", done.stdout)

    def test_the_mode_reaches_every_script(self) -> None:
        self.run_dispatcher("pressure")
        self.assertEqual(self.marker("a-pass"), "pressure pass-c")
        self.assertEqual(self.marker("b-fail"), "pressure fail-c")

    def test_passing_and_skipped_apps_exit_zero(self) -> None:
        for leftover in (self.manifest / "b-fail").iterdir():
            leftover.unlink()
        (self.manifest / "b-fail").rmdir()
        done = self.run_dispatcher("routine")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_an_unknown_mode_runs_nothing(self) -> None:
        done = self.run_dispatcher("now")
        self.assertEqual(done.returncode, 64)
        self.assertEqual(list(self.markers.iterdir()), [])


class TestDispatcherSwarm(DispatcherCase, unittest.TestCase):
    def test_a_task_on_another_node_is_skipped(self) -> None:
        self.app("swarm-app", container="remote", mode="swarm")
        done = self.run_dispatcher("routine")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIsNone(self.marker("swarm-app"))

    def test_a_local_task_gets_the_resolved_container_id(self) -> None:
        self.app("swarm-app", container="local", mode="swarm")
        self.run_dispatcher("routine")
        self.assertEqual(self.marker("swarm-app"), "routine cid-swarm-app")

    def test_a_broken_resolver_fails_the_app(self) -> None:
        self.app("swarm-app", container="broken", mode="swarm")
        done = self.run_dispatcher("routine")
        self.assertEqual(done.returncode, 1)
        self.assertIn("garbage collector failed for: swarm-app", done.stderr)

    def test_a_worker_without_a_local_task_is_skipped_quietly(self) -> None:
        self.app("swarm-app", container="worker", mode="swarm")
        done = self.run_dispatcher("routine")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("swarm-app: skipped", done.stdout)
        self.assertNotIn("warning", done.stdout + done.stderr)

    def test_a_service_without_a_running_task_is_skipped_with_a_warning(self) -> None:
        self.app("swarm-app", container="down", mode="swarm")
        done = self.run_dispatcher("routine")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIsNone(self.marker("swarm-app"))
        self.assertIn("swarm-app: warning: skipped", done.stdout)

    def test_an_empty_stack_fails_the_app_by_name(self) -> None:
        self.app("swarm-app", container="local", mode="swarm", stack="")
        done = self.run_dispatcher("routine")
        self.assertEqual(done.returncode, 1)
        self.assertIsNone(self.marker("swarm-app"))
        self.assertIn(
            "garbage_collector.env of swarm-app leaves GARBAGE_COLLECTOR_STACK empty",
            done.stdout,
        )
        self.assertIn("garbage collector failed for: swarm-app", done.stderr)


class TestDispatcherTimeout(DispatcherCase, unittest.TestCase):
    def test_a_hanging_app_is_cut_off_and_named(self) -> None:
        self.app("hang", container="pass-c", body="sleep 30")
        done = self.run_dispatcher("routine", timeout="1")
        self.assertEqual(done.returncode, 1)
        self.assertIn("garbage collector failed for: hang", done.stderr)

    def test_the_budget_reaches_every_script(self) -> None:
        self.app("a-pass", container="pass-c")
        self.run_dispatcher("routine", timeout="17")
        self.assertEqual(self.marker("a-pass.timeout"), "17")

    def test_a_budget_that_is_no_number_of_seconds_runs_nothing(self) -> None:
        self.app("a-pass", container="pass-c")
        for timeout in ("0", "1h", ""):
            with self.subTest(timeout=timeout):
                done = self.run_dispatcher("routine", timeout=timeout)
                self.assertNotEqual(done.returncode, 0)
                self.assertIsNone(self.marker("a-pass"))


if __name__ == "__main__":
    unittest.main()
