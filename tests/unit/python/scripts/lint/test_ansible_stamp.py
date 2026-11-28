"""``scripts/lint/ansible/stamp.sh`` lets ansible-lint skip only an unchanged input.

The fingerprint must move with every YAML file, plugin, configuration file,
tool version and linted file list, and stay put for files ansible-lint never
reads, so a green stamp is never reused after a change it would see.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

LIBRARY = PROJECT_ROOT / "scripts" / "lint" / "ansible" / "stamp.sh"
DEMO_TASKS = f"roles/web-app-demo/{ROLE_FILE_TASKS_MAIN}"
VERSIONS = "#!/bin/sh\nprintf 'ansible-lint 25.1.0\\nansible-core 2.21.4\\nansible absent\\n'\n"


class TestAnsibleLintStamp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.tree = base / "tree"
        self.bin = base / "bin"
        self.home = base / "home"
        for directory in (
            self.tree / "roles" / "web-app-demo" / "tasks",
            self.tree / "plugins" / "filter",
            self.tree / "docs",
            self.bin,
            self.home,
        ):
            directory.mkdir(parents=True)
        self._write(DEMO_TASKS, "- name: demo\n")
        self._write("plugins/filter/demo.py", "VALUE = 1\n")
        self._write(".ansible-lint", "profile: min\n")
        self._write("docs/README.md", "# Demo\n")
        self.interpreter = self.bin / "fake-python"
        self._tool(VERSIONS)
        lint = self.bin / "ansible-lint"
        lint.write_text(f"#!{self.interpreter}\n")
        lint.chmod(0o755)

    def _write(self, relative: str, content: str) -> None:
        (self.tree / relative).write_text(content)

    def _tool(self, script: str) -> None:
        self.interpreter.write_text(script)
        self.interpreter.chmod(0o755)

    def _bash(self, command: str) -> subprocess.CompletedProcess[str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key != "BASH_ENV" and not key.startswith("INFINITO_")
        }
        env["HOME"] = str(self.home)
        env["PATH"] = f"{self.bin}{os.pathsep}{env['PATH']}"
        return subprocess.run(
            ["bash", "-c", f"set -euo pipefail\nsource {LIBRARY}\n{command}"],
            cwd=self.tree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _fingerprint(self, *scope: str) -> str:
        proc = self._bash(f"ansible_lint_fingerprint {' '.join(scope)}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertRegex(proc.stdout.strip(), r"^[0-9a-f]{64}$")
        return proc.stdout.strip()

    def test_a_recorded_fingerprint_matches_until_an_input_changes(self) -> None:
        before = self._fingerprint("all")
        recorded = self._bash(
            f"ansible_lint_stamp_record {before}\nansible_lint_stamp_matches {before}"
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        self._write("plugins/filter/demo.py", "VALUE = 2\n")
        after = self._fingerprint("all")
        self.assertNotEqual(after, before)
        stale = self._bash(f"ansible_lint_stamp_matches {after}")
        self.assertNotEqual(stale.returncode, 0)

    def test_every_input_ansible_lint_reads_moves_the_fingerprint(self) -> None:
        changes = {
            "yaml": lambda: self._write(DEMO_TASKS, "- name: changed\n"),
            "config": lambda: self._write(".ansible-lint", "profile: basic\n"),
            "plugin": lambda: self._write("plugins/filter/demo.py", "VALUE = 3\n"),
            "tool": lambda: self._tool(VERSIONS.replace("25.1.0", "25.2.0")),
        }
        for name, change in changes.items():
            with self.subTest(input=name):
                before = self._fingerprint("all")
                change()
                self.assertNotEqual(self._fingerprint("all"), before)

    def test_a_file_ansible_lint_never_reads_keeps_the_fingerprint(self) -> None:
        before = self._fingerprint("all")
        self._write("docs/README.md", "# Changed\n")
        self.assertEqual(self._fingerprint("all"), before)

    def test_the_scope_and_the_linted_files_are_part_of_the_fingerprint(self) -> None:
        full = self._fingerprint("all")
        one = self._fingerprint("diff", DEMO_TASKS)
        other = self._fingerprint("diff", ".ansible-lint")
        self.assertEqual(len({full, one, other}), 3)

    def test_unreadable_tool_versions_never_match(self) -> None:
        self._tool("#!/bin/sh\nexit 1\n")
        proc = self._bash("ansible_lint_fingerprint all")
        self.assertNotEqual(proc.returncode, 0)

        empty = self._bash(
            'ansible_lint_stamp_record ""\nansible_lint_stamp_matches ""'
        )
        self.assertNotEqual(empty.returncode, 0)
        self.assertFalse((self.tree / "build" / "ansible-lint.stamp").exists())

    def test_the_yaml_scope_ignores_plugins(self) -> None:
        before = self._fingerprint("yaml")
        self._write("plugins/filter/demo.py", "VALUE = 4\n")
        self.assertEqual(self._fingerprint("yaml"), before)
        shutil.rmtree(self.bin)
        self.assertEqual(self._fingerprint("yaml"), before)


if __name__ == "__main__":
    unittest.main()
