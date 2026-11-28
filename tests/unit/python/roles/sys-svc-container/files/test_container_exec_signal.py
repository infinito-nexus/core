from __future__ import annotations

import contextlib
import importlib.util
import io
import signal
import unittest

from . import PROJECT_ROOT

CONTAINER_PY = (
    PROJECT_ROOT / "roles" / "sys-svc-container" / "files" / "python" / "container.py"
)

spec = importlib.util.spec_from_file_location("container_exec_signal", CONTAINER_PY)
container = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(container)


def _run(cmd: list[str]) -> tuple[int, str]:
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        code = container.exec_docker(cmd, debug=False)
    return code, stderr.getvalue()


class TestExecDockerSignal(unittest.TestCase):
    def test_a_killed_process_reports_its_signal_and_the_shell_code(self) -> None:
        code, stderr = _run(["sh", "-c", f"kill -{signal.SIGHUP.value} $$"])
        self.assertEqual(code, 128 + signal.SIGHUP.value)
        self.assertIn(f"killed by signal {signal.SIGHUP.value}", stderr)
        self.assertNotEqual(
            code % 256,
            255,
            "SystemExit(-1) ends the wrapper with 255, the code docker itself "
            "uses, so a SIGHUP of the docker CLI read as a silent exec failure",
        )

    def test_an_exit_code_passes_through_silently(self) -> None:
        self.assertEqual(_run(["sh", "-c", "exit 255"]), (255, ""))


if __name__ == "__main__":
    unittest.main()
