import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/dsk-gnt-claude"
SCRIPT = ROLE_DIR / "files/shell/claude-gateway.sh"
ENV_PATH = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))["agnt_claude_env_path"]
SOURCED = re.compile(r"^\s*(?:source|\.)\s+(\S+)\s*$", re.MULTILINE)

CLAUDE_STUB = """#!/usr/bin/env bash
printf '%s\\n' "${ANTHROPIC_BASE_URL}" "${ANTHROPIC_AUTH_TOKEN}" "${ANTHROPIC_MODEL}" "$@" >"${STUB_LOG}"
"""

SETTINGS = (
    "ANTHROPIC_BASE_URL=http://127.0.0.1:8081\n"
    "ANTHROPIC_AUTH_TOKEN='sk-workstation key'\n"
    "ANTHROPIC_MODEL=anthropic/claude-sonnet-4-5\n"
)


class TestClaudeGateway(unittest.TestCase):
    def run_launcher(self, settings, *args):
        """Run a copy of the launcher that sources a scratch env file.

        Args:
            settings: content of the env file, None for no file.
            args: the arguments the launcher receives.

        Returns:
            Tuple of the exit code and the lines the stub claude wrote.
        """
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "claude-gateway.env"
            if settings is not None:
                env_file.write_text(settings)
            copy = read_text(str(SCRIPT)).replace(ENV_PATH, str(env_file))
            self.assertEqual(SOURCED.findall(copy), [str(env_file)])
            launcher = Path(tmp) / "claude-gateway.sh"
            launcher.write_text(copy)
            bindir = Path(tmp) / "bin"
            bindir.mkdir()
            stub = bindir / "claude"
            stub.write_text(CLAUDE_STUB)
            stub.chmod(0o755)
            log = Path(tmp) / "claude.log"
            done = subprocess.run(
                ["bash", str(launcher), *args],
                env={
                    "PATH": f"{bindir}:/usr/bin:/bin",
                    "STUB_LOG": str(log),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            lines = read_text(str(log)).splitlines() if log.exists() else []
            return done.returncode, lines

    def test_the_launcher_sources_exactly_the_role_env_path(self):
        self.assertEqual(SOURCED.findall(read_text(str(SCRIPT))), [ENV_PATH])

    def test_the_settings_and_arguments_reach_claude(self):
        rc, lines = self.run_launcher(SETTINGS, "--resume", "two words")
        self.assertEqual(rc, 0)
        self.assertEqual(
            lines,
            [
                "http://127.0.0.1:8081",
                "sk-workstation key",
                "anthropic/claude-sonnet-4-5",
                "--resume",
                "two words",
            ],
        )

    def test_missing_settings_stop_before_claude_starts(self):
        rc, lines = self.run_launcher(None)
        self.assertNotEqual(rc, 0)
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
