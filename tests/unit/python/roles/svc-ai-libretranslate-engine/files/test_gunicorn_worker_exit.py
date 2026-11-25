from __future__ import annotations

import re
import subprocess
import sys
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "svc-ai-libretranslate-engine"
HOOK = ROLE / "files" / "python" / "gunicorn_worker_exit.py"
DOCKERFILE = ROLE / "files" / "Dockerfile"
CORE = ROLE / "tasks" / "00_core.yml"
LOAD_HOOK = """
import importlib.util
import os
import sys
import threading
import types

spec = importlib.util.spec_from_file_location("gunicorn_worker_exit", sys.argv[1])
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
"""
RECYCLED_WORKER = (
    LOAD_HOOK
    + """
threading.Thread(target=threading.Event().wait).start()
try:
    sys.exit(3)
finally:
    if sys.argv[2] == "hook":
        hook.worker_exit(None, types.SimpleNamespace(pid=os.getpid()))
"""
)
ARBITER = (
    LOAD_HOOK
    + """
hook.worker_exit(None, types.SimpleNamespace(pid=os.getpid() + 1))
print("alive")
"""
)


def _run(script: str, *args: str, timeout: float) -> subprocess.CompletedProcess:
    """
    Args:
        script: Python source run in a fresh interpreter.
        args: arguments after the hook path.
        timeout: seconds before the interpreter counts as hung.

    Returns:
        The finished process.
    """
    return subprocess.run(
        [sys.executable, "-c", script, str(HOOK), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class TestWorkerExit(unittest.TestCase):
    def test_a_recycled_worker_leaves_with_its_exit_code_past_a_thread_that_never_ends(
        self,
    ) -> None:
        result = _run(RECYCLED_WORKER, "hook", timeout=60)
        self.assertEqual(result.returncode, 3, result.stderr)

    def test_without_the_hook_the_same_worker_hangs_in_interpreter_shutdown(
        self,
    ) -> None:
        with self.assertRaises(subprocess.TimeoutExpired):
            _run(RECYCLED_WORKER, "bare", timeout=3)

    def test_the_arbiter_keeps_running_when_the_hook_names_a_vanished_worker(
        self,
    ) -> None:
        result = _run(ARBITER, timeout=60)
        self.assertEqual(
            (result.returncode, result.stdout.strip()), (0, "alive"), result.stderr
        )


class TestImageWiring(unittest.TestCase):
    def test_the_image_appends_the_hook_to_the_gunicorn_config_of_the_entrypoint(
        self,
    ) -> None:
        dockerfile = read_text(str(DOCKERFILE))
        self.assertIn(f"COPY {HOOK.name} /tmp/{HOOK.name}\n", dockerfile)
        self.assertIn("RUN test -f scripts/gunicorn_conf.py \\\n", dockerfile)
        self.assertRegex(
            dockerfile,
            rf"cat /tmp/{re.escape(HOOK.name)}; }} >> scripts/gunicorn_conf\.py",
        )

    def test_the_build_context_receives_the_hook(self) -> None:
        staged = [
            task
            for task in load_yaml_any(str(CORE), default_if_missing=[])
            if "stack_host_copy" in task and HOOK.name in task.get("loop", [])
        ]
        self.assertEqual(
            [task["stack_host_copy"]["src"] for task in staged], ["python/{{ item }}"]
        )


if __name__ == "__main__":
    unittest.main()
