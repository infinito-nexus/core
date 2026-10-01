"""A broken line in test.env fails the CLI test instead of vanishing into stderr.

bash ignores ``set -e`` inside a file sourced as part of an ``&&`` list, so
``set -a && . test.env && set +a && ...`` ran on past any failing line and only
the exit code of the file's last line counted. ``ONION_PORTS=25 80`` ran ``80``
there, left the variable unset, and the svc-net-tor port probe passed on an
empty list.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

RUN_ONE = PROJECT_ROOT / "roles" / "test-e2e-cli" / "tasks" / "run_one.yml"


def _run_command() -> str:
    for task in load_yaml_any(str(RUN_ONE)):
        shell = task.get("ansible.builtin.shell")
        if isinstance(shell, dict) and "test.env" in str(shell.get("cmd", "")):
            return shell["cmd"]
    raise AssertionError(f"no shell task sources test.env in {RUN_ONE}")


def _run(env: str, script: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as stage:
        stage_dir = Path(stage)
        (stage_dir / "test.env").write_text(env, encoding="utf-8")
        (stage_dir / "test.sh").write_text(script, encoding="utf-8")
        cmd = (
            Environment(
                undefined=StrictUndefined,
                autoescape=select_autoescape(default_for_string=False),
            )
            .from_string(_run_command())
            .render(
                _cli_stage_dir=stage,
                _cli_timeout=30,
                _cli_test_script=str(stage_dir / "test.sh"),
            )
        )
        return subprocess.run(
            ["bash", "-c", cmd], capture_output=True, text=True, check=False
        )


class TestRunOneEnvSourcing(unittest.TestCase):
    def test_a_broken_line_fails_before_the_script_runs(self) -> None:
        result = _run("A=1\nPORTS=25 80\nZ=2\n", "echo script-ran\n")
        self.assertNotEqual(
            result.returncode,
            0,
            "a test.env line that fails must fail the CLI test; sourcing it "
            "inside an && list makes bash ignore set -e",
        )
        self.assertNotIn("script-ran", result.stdout)
        self.assertIn("command not found", result.stderr)

    def test_a_valid_env_reaches_the_script_and_its_exit_code_counts(self) -> None:
        result = _run('A=1\nPORTS="25 80"\n', 'printf %s "$PORTS"\nexit 3\n')
        self.assertEqual(result.stdout, "25 80", "test.env values must be exported")
        self.assertEqual(result.returncode, 3, result.stderr)


if __name__ == "__main__":
    unittest.main()
