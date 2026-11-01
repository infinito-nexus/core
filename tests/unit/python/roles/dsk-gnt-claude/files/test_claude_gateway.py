import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/dsk-gnt-claude/files/shell/claude-gateway.sh"

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
        """Run the launcher against a stub claude and a scratch home.

        Args:
            settings: content of the gateway settings file, None for no file.
            args: the arguments the launcher receives.

        Returns:
            Tuple of the exit code and the lines the stub claude wrote.
        """
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            settings_dir = home / ".config" / "claude-gateway"
            settings_dir.mkdir(parents=True)
            if settings is not None:
                (settings_dir / "env").write_text(settings)
            bindir = Path(tmp) / "bin"
            bindir.mkdir()
            stub = bindir / "claude"
            stub.write_text(CLAUDE_STUB)
            stub.chmod(0o755)
            log = Path(tmp) / "claude.log"
            done = subprocess.run(
                ["bash", str(SCRIPT), *args],
                env={
                    "HOME": str(home),
                    "PATH": f"{bindir}:/usr/bin:/bin",
                    "STUB_LOG": str(log),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            lines = read_text(str(log)).splitlines() if log.exists() else []
            return done.returncode, lines

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
