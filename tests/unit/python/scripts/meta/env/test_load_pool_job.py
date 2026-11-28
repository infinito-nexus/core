from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.runner.role import project_prefix

LOADER_DIR = Path(PROJECT_ROOT) / "scripts" / "meta" / "env"
ATTACH = ("cli", "administration", "deploy", "pool", "attach")
SOCKET = "unix:///var/cache/infinito/core/cache/jobs/docker.sock"
STUB = f"""
import sys

if sys.argv[1] == "gone":
    print("[runner] no job gone", file=sys.stderr)
    sys.exit(2)
print("{SOCKET}")
print("runner-" + sys.argv[1])
"""
SHOWN = ("DOCKER_HOST", "INFINITO_STACK_NAME", "INFINITO_CONTAINER")
SHOW = "printf '%s\\n' " + " ".join(f'"{key}=${{{key}:-}}"' for key in SHOWN)


class TestPoolJob(unittest.TestCase):
    def setUp(self) -> None:
        self.checkout = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.checkout)
        loader = self.checkout / "scripts" / "meta" / "env"
        loader.mkdir(parents=True)
        for name in ("load.sh", "python.sh"):
            shutil.copy(LOADER_DIR / name, loader)
        (self.checkout / ".env").write_text(
            "INFINITO_DISTRO=debian\n", encoding="utf-8"
        )
        package = self.checkout
        for part in ATTACH:
            package = package / part
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "__main__.py").write_text(STUB, encoding="utf-8")

    def _load(self, steps: str) -> tuple[int, dict[str, str], str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("INFINITO_")
            and key not in ("BASH_ENV", "DOCKER_HOST", "PYTHONPATH", "VIRTUAL_ENV")
        }
        env["PYTHONPATH"] = str(self.checkout)
        done = subprocess.run(
            [
                "bash",
                "-c",
                f"{steps}\nsource scripts/meta/env/load.sh\n{SHOW}",
            ],
            env=env,
            cwd=self.checkout,
            capture_output=True,
            text=True,
            check=False,
        )
        shown = dict(line.split("=", 1) for line in done.stdout.splitlines())
        return done.returncode, shown, done.stderr

    def test_a_pool_job_points_docker_and_the_stack_at_its_stack(self) -> None:
        code, shown, err = self._load("export INFINITO_POOL_JOB=3")
        self.assertEqual(code, 0, err)
        self.assertEqual(
            shown,
            {
                "DOCKER_HOST": SOCKET,
                "INFINITO_STACK_NAME": "runner-3",
                "INFINITO_CONTAINER": "infinito_nexus_runner_3",
            },
        )

    def test_a_second_load_keeps_the_pool_job(self) -> None:
        code, shown, err = self._load(
            "export INFINITO_POOL_JOB=3\nsource scripts/meta/env/load.sh"
        )
        self.assertEqual([code, shown["DOCKER_HOST"]], [0, SOCKET], err)
        self.assertEqual(shown["INFINITO_STACK_NAME"], "runner-3")

    def test_without_a_pool_job_the_loader_changes_nothing(self) -> None:
        code, shown, err = self._load("export DOCKER_HOST=unix:///run/own.sock")
        self.assertEqual(code, 0, err)
        self.assertEqual(
            [shown["DOCKER_HOST"], shown["INFINITO_STACK_NAME"]],
            ["unix:///run/own.sock", ""],
        )
        code, shown, err = self._load("")
        self.assertEqual(
            [code, shown["DOCKER_HOST"], shown["INFINITO_STACK_NAME"]], [0, "", ""]
        )

    def test_a_job_without_a_stack_stops_the_caller(self) -> None:
        code, shown, err = self._load("export INFINITO_POOL_JOB=gone")
        self.assertEqual([code, shown], [2, {}])
        self.assertIn("no job gone", err)

    def test_a_pool_stack_name_without_a_job_stops_the_caller(self) -> None:
        for steps in (
            "export INFINITO_STACK_NAME=runner-2",
            "export INFINITO_STACK_NAME=runner-2 INFINITO_POOL_RUNNER=false",
        ):
            code, shown, err = self._load(steps)
            with self.subTest(steps=steps):
                self.assertEqual([code, shown], [2, {}])
                self.assertIn("job=<id>", err)

    def test_the_pool_runner_itself_and_other_stack_names_load(self) -> None:
        for steps, stack in (
            (
                "export INFINITO_STACK_NAME=runner-2 INFINITO_POOL_RUNNER=true",
                "runner-2",
            ),
            ("export INFINITO_STACK_NAME=runner-0", "runner-0"),
            ("export INFINITO_STACK_NAME=runner-x", "runner-x"),
            ("export INFINITO_STACK_NAME=myrunner-2", "myrunner-2"),
        ):
            code, shown, err = self._load(steps)
            with self.subTest(steps=steps):
                self.assertEqual([code, shown["INFINITO_STACK_NAME"]], [0, stack], err)

    def test_the_refused_prefix_is_the_one_svc_runner_names_its_stacks_with(
        self,
    ) -> None:
        loader = read_text(str(LOADER_DIR / "load.sh"))
        self.assertIn(f"=~ ^{project_prefix()}-[1-9][0-9]*$ ]]", loader)


if __name__ == "__main__":
    unittest.main()
