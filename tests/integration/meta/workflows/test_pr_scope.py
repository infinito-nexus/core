import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "scripts" / "meta" / "resolve" / "pr" / "scope.sh"


@unittest.skipUnless(
    shutil.which("jq"), "jq is required for the shell script under test"
)
class TestPullRequestScope(unittest.TestCase):
    def _write_fake_gh(self, temp_dir: Path) -> None:
        fake_gh = temp_dir / "gh"
        fake_gh.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                if [[ "${1:-}" != "api" ]]; then
                    echo "Unsupported gh invocation: $*" >&2
                    exit 1
                fi

                printf '%s\n' "${GH_FAKE_PULL_FILES_JSON:-}"
                """
            ),
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)

    def _run_script(self, *, files_json: str):
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            output_file = temp_dir / "output.txt"

            self._write_fake_gh(temp_dir)

            env = os.environ.copy()
            env.update(
                {
                    "PR_NUMBER": "42",
                    "REPOSITORY": "kevinveenbirkenbach/infinito-nexus",
                    "GH_TOKEN": "test-token",
                    "GITHUB_OUTPUT": str(output_file),
                    "GH_FAKE_PULL_FILES_JSON": files_json,
                    "PATH": f"{temp_dir}:{env['PATH']}",
                }
            )

            result = subprocess.run(
                ["bash", str(SCRIPT_PATH)],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            outputs = {}
            for line in read_text(str(output_file)).splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                outputs[key] = value

            return result, outputs

    def test_agents_only_scope_skips_ci_orchestrator(self):
        files_json = """\
[
  {"filename":"AGENTS.md"},
  {"filename":"docs/agents/action/debug/local.md"},
  {"filename":"docs/agents/action/develop.md"}
]
"""
        _, outputs = self._run_script(files_json=files_json)
        self.assertEqual(outputs["scope"], "agents")
        self.assertEqual(outputs["run_ci_orchestrator"], "false")

    def test_documentation_only_scope_skips_ci_orchestrator(self):
        files_json = """\
[
  {"filename":"README.md"},
  {"filename":"docs/contributing/flow/pull-request.md"},
  {"filename":".github/PULL_REQUEST_TEMPLATE/documentation.md"},
  {"filename":"docs/contributing/setup.rst"}
]
"""
        _, outputs = self._run_script(files_json=files_json)
        self.assertEqual(outputs["scope"], "documentation")
        self.assertEqual(outputs["run_ci_orchestrator"], "false")

    def test_renamed_agent_file_falls_back_to_full_ci(self):
        files_json = """\
[
  {
    "status": "renamed",
    "filename": "docs/contributing/flow/workflow.md",
    "previous_filename": "AGENTS.md"
  }
]
"""
        _, outputs = self._run_script(files_json=files_json)
        self.assertEqual(outputs["scope"], "full")
        self.assertEqual(outputs["run_ci_orchestrator"], "true")


if __name__ == "__main__":
    unittest.main()
