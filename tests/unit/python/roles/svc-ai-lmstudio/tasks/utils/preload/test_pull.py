from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

PULL = PROJECT_ROOT / "roles/svc-ai-lmstudio/tasks/utils/preload/pull.yml"
WRAPPER = PROJECT_ROOT / "roles/sys-svc-container/files/python/container.py"
TASK = "⬇️ Pre-pull LM Studio models"
BUDGET_SECONDS = 2

FAKE_DOCKER = """
import shutil
import subprocess
import sys

args = sys.argv[2:]
flags = []
while args[0].startswith("-"):
    flags.append(args.pop(0))
child = subprocess.Popen(
    args[1:],
    stdin=None if "-i" in flags else subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
shutil.copyfileobj(child.stdout, sys.stdout.buffer)
sys.exit(child.wait())
"""

FAKE_LMS = """
import os
import signal
import sys
import time
from pathlib import Path

state = Path(os.environ["FAKE_LMS_STATE"])
job = state / "job"


def record(name, line):
    with (state / name).open("a") as handle:
        handle.write(line + "\\n")


def interrupted(signum, frame):
    if sys.stdin.readline().strip().upper() == "N":
        job.unlink()
        record("events", "cancel")
    else:
        record("events", "background")
    sys.exit(1)


signal.signal(signal.SIGINT, interrupted)
record("pids", str(os.getpid()))
if job.exists():
    record("events", "attach")
else:
    job.touch()
    record("events", "start")
time.sleep(30)
"""


def _install(path: Path, content: str) -> None:
    """
    Args:
        path: where the executable lands.
        content: its full text, shebang included.
    """
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _lines(path: Path) -> list[str]:
    """
    Args:
        path: a record the fake lms appends to.

    Returns:
        Its lines, or [] while it does not exist.
    """
    if not path.exists():
        return []
    return path.read_text().split()  # nocheck: cache-read  rewritten between reads


def _running(pid: int) -> bool:
    """
    Args:
        pid: a fake lms process.

    Returns:
        Whether it still runs.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _templar() -> tuple[dict, Templar]:
    """
    Returns:
        The pre-pull task and a templar holding one model whose budget is BUDGET_SECONDS.
    """
    task = next(
        task
        for task in load_yaml_any(str(PULL), default_if_missing=[])
        if task.get("name") == TASK
    )
    variables = {
        "LMSTUDIO_LOCAL_CID": "lmstudio",
        "LMSTUDIO_PRELOAD_FLOOR_SECONDS": BUDGET_SECONDS,
        "LMSTUDIO_PRELOAD_MIN_BYTES_PER_SECOND": 1_000_000,
        "model": {
            "alias": "llama3.2:1b",
            "source": "https://huggingface.co/lmstudio-community/Llama-3.2-1B-Instruct-GGUF",
            "quant": "Q4_K_M",
            "bytes": 1,
        },
    }
    for key, value in (task.get("vars") or {}).items():
        variables[key] = _trust_as_template(value)
    return task, Templar(loader=DataLoader(), variables=variables)


def _render(templar: Templar, value: str) -> str:
    """
    Args:
        templar: from _templar.
        value: a task field.

    Returns:
        The field rendered.
    """
    return str(templar.template(_trust_as_template(value)))


class TestTimedOutPull(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scratch = tempfile.TemporaryDirectory()
        root = Path(cls.scratch.name)
        bin_dir = root / "bin"
        cls.state = root / "state"
        bin_dir.mkdir()
        cls.state.mkdir()
        _install(bin_dir / "docker", f"#!{sys.executable} -I\n{FAKE_DOCKER}")
        _install(bin_dir / "lms", f"#!{sys.executable} -I\n{FAKE_LMS}")
        _install(
            bin_dir / "container",
            f'#!/bin/sh\nexec "{sys.executable}" -I "{WRAPPER}" "$@"\n',
        )
        task, cls.templar = _templar()
        command = _render(cls.templar, task["ansible.builtin.shell"])
        cls.environment = {
            key: _render(cls.templar, value)
            for key, value in task["environment"].items()
        }
        env = {
            **os.environ,
            **cls.environment,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_LMS_STATE": str(cls.state),
        }
        cls.attempts = []
        for _attempt in range(2):
            result = subprocess.run(
                ["/bin/sh", "-c", command],
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=120,
            )
            pid = int(_lines(cls.state / "pids")[-1])
            cls.attempts.append((result.returncode, _running(pid)))
        cls.events = _lines(cls.state / "events")

    @classmethod
    def tearDownClass(cls) -> None:
        for pid in map(int, _lines(cls.state / "pids")):
            if _running(pid):
                os.kill(pid, signal.SIGKILL)
        cls.scratch.cleanup()

    def test_the_timeout_still_fails_the_attempt(self) -> None:
        self.assertEqual([rc for rc, _alive in self.attempts], [124, 124])

    def test_no_lms_outlives_its_attempt(self) -> None:
        self.assertEqual([alive for _rc, alive in self.attempts], [False, False])

    def test_the_timeout_cancels_the_transfer(self) -> None:
        self.assertEqual(self.events[:2], ["start", "cancel"])

    def test_the_retry_downloads_afresh(self) -> None:
        self.assertEqual(self.events, ["start", "cancel", "start", "cancel"])

    def test_the_host_guard_outlasts_the_in_container_cancel(self) -> None:
        self.assertGreater(
            int(self.environment["CONTAINER_EXEC_TIMEOUT"]),
            int(_render(self.templar, "{{ (_budget | int) + (_grace | int) }}")),
        )


if __name__ == "__main__":
    unittest.main()
