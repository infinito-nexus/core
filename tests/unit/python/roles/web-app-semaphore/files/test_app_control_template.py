"""The script every stop and start template runs."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-semaphore"
    / "files"
    / "shell"
    / "repository"
    / "app-control.sh"
)
FAKE_SSH = """#!/usr/bin/env bash
printf 'CALL %s\\n' "$*" >>"${SSH_LOG}"
for arg in "$@"; do
	case "${arg}" in
	UserKnownHostsFile=*) cat "${arg#UserKnownHostsFile=}" >>"${SSH_LOG}" ;;
	esac
done
"""
KNOWN = "host.docker.internal ssh-ed25519 AAAAhostkey"


class TemplateScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        ssh = bin_dir / "ssh"
        ssh.write_text(FAKE_SSH, encoding="utf-8")
        ssh.chmod(0o755)
        self.log = root / "ssh.log"
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "SSH_LOG": str(self.log),
            "APP_CONTROL_TARGETS": "app-control@host.docker.internal",
            "APP_CONTROL_KNOWN_HOSTS": KNOWN,
            "SSH_AUTH_SOCK": str(root / "agent.sock"),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, **overrides):
        env = {**self.env, **overrides}
        env = {key: value for key, value in env.items() if value is not None}
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self):
        if not self.log.exists():
            return []
        lines = self.log.read_text(
            encoding="utf-8"
        ).splitlines()  # nocheck: cache-read tempdir
        return [line[len("CALL ") :] for line in lines if line.startswith("CALL ")]

    def test_stop_sends_exactly_the_app_control_command_with_the_host_key_pinned(self):
        result = self.run_script("stop", "web-app-wiki")
        self.assertEqual(result.returncode, 0, result.stderr)
        [call] = self.calls()
        self.assertTrue(
            call.endswith(
                "app-control@host.docker.internal app-control stop web-app-wiki"
            )
        )
        self.assertIn("-o StrictHostKeyChecking=yes", call)
        self.assertIn("-o BatchMode=yes", call)
        logged = self.log.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertIn(KNOWN, logged)

    def test_all_reaches_every_target(self):
        result = self.run_script(
            "start",
            "all",
            APP_CONTROL_TARGETS="app-control@one.example app-control@two.example",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [call.rsplit(" ", 4)[1:] for call in self.calls()],
            [
                ["app-control@one.example", "app-control", "start", "all"],
                ["app-control@two.example", "app-control", "start", "all"],
            ],
        )

    def test_anything_but_one_action_and_one_application_is_refused(self):
        for args in (
            (),
            ("stop",),
            ("reconcile", "web-app-wiki"),
            ("stop", "web-app-wiki", "extra"),
            ("stop", "../etc"),
            ("stop", "web-app-wiki;id"),
            ("stop", "Web-App"),
        ):
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertEqual(result.returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_without_the_inventory_key_nothing_is_sent(self):
        result = self.run_script("stop", "web-app-wiki", SSH_AUTH_SOCK=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
