from __future__ import annotations

import http.server
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

INSTALL = (
    PROJECT_ROOT / "roles/svc-ai-libretranslate-engine/tasks/utils/install_models.yml"
)
WAIT = "⏳ Wait until {{ application_id }} finished its own boot"
PREFETCH = "📥 Install the Argos models into {{ application_id }}"
FAKE_CONTAINER = '#!/bin/sh\nshift 2\nexec "$@"\n'
RESTARTING = (
    "Error response from daemon: Container "
    "19e44fa354e545a1007b37cfee53f6e064b8c5cbc9ca57a6b2cc09503874ba16"
    " is restarting, wait until the container is running"
)
FAKE_RESTARTING = f"#!/bin/sh\necho '{RESTARTING}' >&2\nexit 1\n"
FAKE_KILLED = "#!/bin/sh\nexit 137\n"
DEAD_PROXY = "http://127.0.0.1:9"


def _tasks() -> list[dict]:
    """
    Returns:
        The model install tasks.
    """
    return load_yaml_any(str(INSTALL), default_if_missing=[])


def _render(task: dict, value: str, variables: dict) -> str:
    """
    Args:
        task: the task whose own vars join the context.
        value: a task field.
        variables: the play variables the field reads.

    Returns:
        The field rendered.
    """
    context = dict(variables)
    for key, raw in (task.get("vars") or {}).items():
        context[key] = _trust_as_template(raw)
    templar = Templar(loader=DataLoader(), variables=context)
    return str(templar.template(_trust_as_template(str(value))))


class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(self.server.status)
        self.end_headers()

    def log_message(self, *_: object) -> None:
        return


class TestBootProbe(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        self.container = bin_dir / "container"
        self.container.write_text(FAKE_CONTAINER)
        self.container.chmod(0o755)
        (self.root / "venv" / "bin").mkdir(parents=True)
        (self.root / "venv" / "bin" / "python").symlink_to(sys.executable)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HTTP_PROXY": DEAD_PROXY,
            "http_proxy": DEAD_PROXY,
        }
        self.env.pop("NO_PROXY", None)
        self.env.pop("no_proxy", None)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Health)
        self.server.status = 200
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _attempt(self, port: int) -> tuple[bool, bool]:
        """
        Args:
            port: where the probe looks for the engine.

        Returns:
            Whether the wait stops after this attempt, and whether it fails.
        """
        task = next(task for task in _tasks() if task.get("name") == WAIT)
        command = _render(
            task,
            task["ansible.builtin.shell"],
            {
                "LIBRETRANSLATE_ENGINE_LOCAL_CID": "engine",
                "LIBRETRANSLATE_ENGINE_PORT": port,
            },
        )
        run = subprocess.run(
            ["/bin/sh", "-c", command],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        result = {
            "libretranslate_engine_boot": {
                "rc": run.returncode,
                "stdout": run.stdout,
                "stderr": run.stderr,
            }
        }
        return tuple(
            _render(task, f"{{{{ {task[key]} }}}}", result) == "True"
            for key in ("until", "failed_when")
        )

    def _container(self, script: str) -> None:
        self.container.write_text(script)

    def test_a_booted_engine_ends_the_wait(self) -> None:
        self.assertEqual(self._attempt(self.server.server_address[1]), (True, False))

    def test_a_failing_health_endpoint_keeps_waiting(self) -> None:
        self.server.status = 503

        self.assertFalse(self._attempt(self.server.server_address[1])[0])

    def test_an_engine_still_in_its_boot_install_keeps_waiting(self) -> None:
        closed = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Health)
        port = closed.server_address[1]
        closed.server_close()

        self.assertFalse(self._attempt(port)[0])

    def test_a_restarting_container_fails_the_wait_after_one_try(self) -> None:
        self._container(FAKE_RESTARTING)

        self.assertEqual(self._attempt(self.server.server_address[1]), (True, True))

    def test_a_killed_exec_fails_the_wait_after_one_try(self) -> None:
        self._container(FAKE_KILLED)

        self.assertEqual(self._attempt(self.server.server_address[1]), (True, True))


class TestWaitPlacement(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = _tasks()
        self.names = [task.get("name") for task in self.tasks]
        self.wait = self.tasks[self.names.index(WAIT)]

    def test_the_wait_runs_before_the_prefetch_and_outside_its_retries(self) -> None:
        self.assertLess(self.names.index(WAIT), self.names.index(PREFETCH))
        self.assertNotIn(
            "health",
            self.tasks[self.names.index(PREFETCH)]["ansible.builtin.shell"]["cmd"],
        )

    def test_the_wait_budget_is_the_configured_prefetch_timeout(self) -> None:
        for budget in (1800, 60):
            variables = {"LIBRETRANSLATE_ENGINE_PREFETCH_TIMEOUT": budget}
            retries = int(_render(self.wait, self.wait["retries"], variables))
            delay = int(_render(self.wait, self.wait["delay"], variables))

            self.assertEqual(retries * delay, budget)


if __name__ == "__main__":
    unittest.main()
