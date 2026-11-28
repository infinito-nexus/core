from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.runner.loop import CHECKOUT_KEY, IMAGE_KEY, INSTALL_KEY, ROOTS_KEY

SERVE_MODULE = "cli.administration.deploy.pool.serve.__main__"
PROBE = """
import importlib, os, subprocess, sys, tempfile
from pathlib import Path

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo))
before = set(sys.modules)
serve = importlib.import_module(sys.argv[2])
for extra in sys.argv[3:]:
    importlib.import_module(extra)
from utils.runner import jobs, loop


class Stop(Exception):
    pass


def stop(_seconds):
    raise Stop


def run(argv, **_kwargs):
    return subprocess.CompletedProcess(argv, 0)


with tempfile.TemporaryDirectory() as tmp:
    base = Path(os.path.realpath(tmp))
    roots = base / "worktrees"
    (roots / "core" / loop.ENTRY).parent.mkdir(parents=True)
    (roots / "core" / loop.ENTRY).write_text("#!/bin/sh\\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=roots / "core", check=True)
    install = base / "install" / "1"
    install.mkdir(parents=True)
    queue, runner = serve.settings(
        {
            serve.QUEUE_KEY: str(base / "jobs"),
            serve.COMPOSE_KEY: "runner-1",
            serve.SRC_KEY: str(roots / "core"),
            loop.ROOTS_KEY: str(roots),
            loop.INSTALL_KEY: str(install),
            loop.CHECKOUT_KEY: str(install / "checkout"),
            loop.IMAGE_KEY: "toolchain",
        }
    )
    record = jobs.submit(queue, str(roots / "core"), "compose-deploy", [], False, 0.0)
    try:
        loop.serve(queue, runner, run, lambda: 0.0, stop, 0, serve.teardown)
    except Stop:
        pass
    print(jobs.job(queue, record.id).state)
loaded = {name.split(".")[0] for name in set(sys.modules) - before}
foreign = sorted(
    top
    for top in loaded
    if top not in sys.stdlib_module_names and not (repo / top).is_dir()
)
print(" ".join(foreign))
"""


def _probe(*extra: str) -> tuple[str, list[str], str]:
    done = subprocess.run(
        [sys.executable, "-I", "-c", PROBE, str(PROJECT_ROOT), SERVE_MODULE, *extra],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = done.stdout.splitlines()
    state = lines[0] if lines else ""
    foreign = lines[1].split() if len(lines) > 1 else []
    return state, foreign, done.stderr


class TestThePoolLoopRunsOnTheBarePython(unittest.TestCase):
    def test_it_imports_and_runs_a_job_on_the_stdlib_and_the_repo_alone(
        self,
    ) -> None:
        state, foreign, stderr = _probe()
        self.assertEqual(state, "done", stderr)
        self.assertEqual(
            foreign,
            [],
            "the runner image ships python3 without third-party packages; "
            "keep YAML and other third-party reads in host-side modules such "
            "as utils.runner.role",
        )

    def test_a_module_that_needs_pyyaml_on_the_way_is_reported(self) -> None:
        state, foreign, stderr = _probe("utils.cache.yaml")
        self.assertEqual(state, "done", stderr)
        self.assertIn("yaml", foreign)

    def test_the_host_side_role_module_stays_out_of_the_loop(self) -> None:
        _state, foreign, _stderr = _probe("utils.runner.role")
        self.assertIn("yaml", foreign)


class TestTheRunnerSettings(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(os.path.realpath(self._tmp.name))
        self.serve = importlib.import_module(SERVE_MODULE)
        self.env = {
            self.serve.QUEUE_KEY: str(self.base / "cache" / "jobs"),
            self.serve.COMPOSE_KEY: "runner-1",
            self.serve.SRC_KEY: str(self.base / "Repositories" / "core"),
            ROOTS_KEY: str(self.base / "Repositories"),
            INSTALL_KEY: str(self.base / "runner" / "1"),
            CHECKOUT_KEY: str(self.base / "runner" / "1" / "checkout"),
            IMAGE_KEY: "infinito/arch:0123abcd",
        }

    def _refusal(self, **changed: str) -> str:
        with self.assertRaises(SystemExit) as raised:
            self.serve.settings({**self.env, **changed})
        return str(raised.exception.code)

    def test_a_runner_copies_its_jobs_into_its_own_directory(self) -> None:
        _queue, runner = self.serve.settings(self.env)
        self.assertEqual(
            [runner.install, runner.checkout],
            [self.base / "runner" / "1", self.base / "runner" / "1" / "checkout"],
        )

    def test_a_runner_without_an_absolute_job_directory_does_not_start(self) -> None:
        for checkout in ("", "checkout", "./checkout"):
            with self.subTest(checkout=checkout):
                self.assertIn(CHECKOUT_KEY, self._refusal(**{CHECKOUT_KEY: checkout}))
        env = dict(self.env)
        del env[CHECKOUT_KEY]
        with self.assertRaises(SystemExit):
            self.serve.settings(env)

    def test_a_runner_without_its_image_does_not_start(self) -> None:
        self.assertIn(IMAGE_KEY, self._refusal(**{IMAGE_KEY: ""}))
        _queue, runner = self.serve.settings(self.env)
        self.assertEqual(runner.image, self.env[IMAGE_KEY])

    def test_a_linked_path_does_not_start(self) -> None:
        (self.base / "real").mkdir()
        (self.base / "link").symlink_to(self.base / "real")
        refusal = self._refusal(**{INSTALL_KEY: str(self.base / "link")})
        self.assertIn("is or lies below a link", refusal)

    def test_overlapping_queue_install_and_roots_do_not_start(self) -> None:
        for key, path in (
            (self.serve.QUEUE_KEY, self.env[ROOTS_KEY] + "/jobs"),
            (INSTALL_KEY, self.env[ROOTS_KEY]),
            (self.serve.QUEUE_KEY, str(self.base / "runner")),
        ):
            with self.subTest(key=key, path=path):
                self.assertIn("overlap", self._refusal(**{key: path}))

    def test_a_loop_checkout_outside_every_root_does_not_start(self) -> None:
        refusal = self._refusal(**{self.serve.SRC_KEY: str(self.base / "elsewhere")})
        self.assertIn("lies outside every worktree root", refusal)

    def test_a_job_folder_outside_the_install_directory_does_not_start(self) -> None:
        refusal = self._refusal(**{CHECKOUT_KEY: str(self.base / "checkout")})
        self.assertIn(f"is no folder of {INSTALL_KEY}", refusal)


if __name__ == "__main__":
    unittest.main()
