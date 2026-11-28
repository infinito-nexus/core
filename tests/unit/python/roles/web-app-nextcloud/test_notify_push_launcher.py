from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

LAUNCHER = (
    PROJECT_ROOT
    / "roles/web-app-nextcloud/files/shell/addons/notify_push/notify-push.sh"
)


def _arch() -> str:
    machine = os.uname().machine
    if machine.startswith("armv7"):
        return "armv7"
    if machine.startswith("aarch64"):
        return "aarch64"
    return machine


def _run(app_directory: Path, port: int, *args: str, timeout: float = 10):
    return subprocess.run(
        ["sh", str(LAUNCHER), *args],
        env={
            "PATH": os.environ["PATH"],
            "NOTIFY_PUSH_APP_DIRECTORY": str(app_directory),
            "PORT": str(port),
        },
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _place_binary(app_directory: Path, mode: int) -> None:
    binary = app_directory / "bin" / _arch() / "notify_push"
    binary.parent.mkdir(parents=True)
    binary.write_text('#!/bin/sh\necho "daemon on port $PORT"\n')
    binary.chmod(mode)


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class TestNotifyPushLauncher(unittest.TestCase):
    def test_health_passes_while_the_app_has_not_placed_its_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_run(Path(tmp), _closed_port(), "health").returncode, 0)

    def test_health_passes_while_the_placed_binary_is_not_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            _place_binary(Path(tmp), 0o644)
            self.assertEqual(_run(Path(tmp), _closed_port(), "health").returncode, 0)

    @unittest.skipUnless(
        shutil.which("php"), "the probe runs php, as the Nextcloud image does"
    )
    def test_health_follows_the_port_once_the_binary_is_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            _place_binary(Path(tmp), 0o755)
            self.assertEqual(_run(Path(tmp), _closed_port(), "health").returncode, 1)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                port = listener.getsockname()[1]
                self.assertEqual(_run(Path(tmp), port, "health").returncode, 0)

    def test_run_execs_the_executable_binary_of_this_architecture(self):
        with tempfile.TemporaryDirectory() as tmp:
            _place_binary(Path(tmp), 0o755)
            result = _run(Path(tmp), 7867, "run")
            self.assertEqual(
                (result.returncode, result.stdout.strip()), (0, "daemon on port 7867")
            )

    def test_run_waits_while_the_binary_is_not_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            _place_binary(Path(tmp), 0o644)
            with self.assertRaises(subprocess.TimeoutExpired):
                _run(Path(tmp), 7867, "run", timeout=2)

    def test_an_unknown_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_run(Path(tmp), 7867, "start").returncode, 64)


if __name__ == "__main__":
    unittest.main()
