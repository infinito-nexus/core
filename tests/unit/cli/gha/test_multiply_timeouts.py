from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "scripts"
    / "tests"
    / "deploy"
    / "ci"
    / "multiply-timeouts.sh"
)


def _run(multiplier: int, repo_root: str) -> None:
    subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            **os.environ,
            "INFINITO_TIMEOUT_MULTIPLIER": str(multiplier),
            "INFINITO_REPO_ROOT": repo_root,
        },
        check=True,
        capture_output=True,
    )


class TestMultiplyTimeouts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        tasks_dir = root / "roles" / "web-app-foo" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "main.yml").write_text(
            textwrap.dedent("""\
            - name: wait
              wait_for:
                port: 80
              retries: 10
              delay: 2
        """)
        )
        compose_dir = root / "roles" / "web-app-foo" / "templates"
        compose_dir.mkdir(parents=True)
        (compose_dir / "compose.yml.j2").write_text(
            textwrap.dedent("""\
            services:
              app:
                healthcheck:
                  start_period: 30s
        """)
        )
        self.root = str(root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_noop_when_multiplier_is_one(self):
        _run(1, self.root)
        self.assertIn(
            "retries: 10",
            (
                Path(self.root) / "roles" / "web-app-foo" / "tasks" / "main.yml"
            ).read_text(),
        )

    def test_multiplies_retries(self):
        _run(3, self.root)
        content = (
            Path(self.root) / "roles" / "web-app-foo" / "tasks" / "main.yml"
        ).read_text()
        self.assertIn("retries: 30", content)

    def test_multiplies_start_period(self):
        _run(3, self.root)
        content = (
            Path(self.root) / "roles" / "web-app-foo" / "templates" / "compose.yml.j2"
        ).read_text()
        self.assertIn("start_period: 90s", content)

    def test_multiplier_zero_is_noop(self):
        _run(0, self.root)
        content = (
            Path(self.root) / "roles" / "web-app-foo" / "tasks" / "main.yml"
        ).read_text()
        self.assertIn("retries: 10", content)


if __name__ == "__main__":
    unittest.main()
