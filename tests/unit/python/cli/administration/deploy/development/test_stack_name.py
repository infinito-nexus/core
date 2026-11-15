"""The compose project name and the container names of a stack.

Without ``INFINITO_STACK_NAME`` every name equals the one compose and the
``.env`` produced before the explicit ``-p``: the normalized checkout basename,
``INFINITO_CONTAINER`` and ``INFINITO_RUNNER_PREFIX`` as ``.env`` holds them.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import ClassVar

from cli.administration.deploy.development.env import compose_file_args
from cli.administration.deploy.development.stack import (
    compose_argv,
    normalize,
    stack_name,
)
from utils.cache.files import PROJECT_ROOT

ROOT = Path(PROJECT_ROOT)
MAIN_CHECKOUT = "infinito-nexus-core"
WORKTREE = "local-stack-092-r4"
SHOWN = (
    "INFINITO_DISTRO",
    "INFINITO_CONTAINER",
    "INFINITO_RUNNER_PREFIX",
    "INFINITO_STACK_NAME",
)


def scratch_dir(test: unittest.TestCase) -> Path:
    path = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, path)
    return path


def clean_env(**overrides: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFINITO_", "COMPOSE_"))
        and k not in ("BASH_ENV", "PYTHONPATH", "VENV", "PYTHON", "VIRTUAL_ENV")
    }
    env["PYTHONPATH"] = str(ROOT)
    env.update(overrides)
    return env


class TestDefaultProjectName(unittest.TestCase):
    def checkout(self, *parts: str) -> Path:
        path = scratch_dir(self).joinpath(*parts)
        path.mkdir(parents=True)
        return path

    def test_main_checkout_keeps_its_implicit_name(self):
        root = self.checkout("Repositories", "github.com", "owner", MAIN_CHECKOUT)
        self.assertEqual(stack_name(root, {}), MAIN_CHECKOUT)

    def test_worktree_keeps_its_implicit_name(self):
        root = self.checkout("worktrees", "core", "feature", "iam-reqs", WORKTREE)
        self.assertEqual(stack_name(root, {}), WORKTREE)

    def test_the_basename_is_normalized_like_compose_does(self):
        self.assertEqual(normalize("Infinito.Nexus_Core"), "infinitonexus_core")
        self.assertEqual(normalize("__-x.Y"), "xy")
        root = self.checkout("Some.Checkout")
        self.assertEqual(stack_name(root, {}), "somecheckout")

    def test_compose_project_name_still_wins_when_no_stack_is_named(self):
        root = self.checkout(WORKTREE)
        env = {"COMPOSE_PROJECT_NAME": "runner-1"}
        self.assertEqual(stack_name(root, env), "runner-1")

    def test_a_symlinked_pwd_names_the_project_like_go_getwd(self):
        base = scratch_dir(self)
        real = base / "real-name"
        real.mkdir()
        (base / "alias").symlink_to(real)
        self.assertEqual(stack_name(real, {"PWD": str(base / "alias")}), "alias")
        self.assertEqual(stack_name(real, {"PWD": str(base)}), "real-name")

    def test_compose_argv_only_adds_the_implicit_project(self):
        before = ["docker", "compose", *compose_file_args()]
        after = compose_argv(ROOT)
        self.assertEqual(
            after[:4], ["docker", "compose", "-p", stack_name(ROOT, os.environ)]
        )
        self.assertEqual([*after[:2], *after[4:]], before)


class TestNamedStack(unittest.TestCase):
    def test_the_stack_name_wins_over_both_implicit_sources(self):
        env = {"INFINITO_STACK_NAME": "demo", "COMPOSE_PROJECT_NAME": "runner-1"}
        self.assertEqual(stack_name(ROOT, env), "demo")

    def test_an_invalid_stack_name_is_refused(self):
        with self.assertRaises(SystemExit):
            stack_name(ROOT, {"INFINITO_STACK_NAME": "Demo.Stack"})

    def test_compose_argv_addresses_the_named_stack(self):
        with mock.patch.dict(os.environ, {"INFINITO_STACK_NAME": "demo"}):
            self.assertEqual(compose_argv(ROOT)[2:4], ["-p", "demo"])


class TestShellHelper(unittest.TestCase):
    def run_helper(self, **overrides: str) -> list[str]:
        bin_dir = scratch_dir(self)
        fake = bin_dir / "docker"
        fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        env = clean_env(
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            VENV=str(Path(sys.executable).parent.parent),
            **overrides,
        )
        proc = subprocess.run(
            [
                "bash",
                "-c",
                "source scripts/meta/compose.sh && infinito_compose ps -q infinito",
            ],
            env=env,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.splitlines()

    def test_unnamed_call_passes_the_implicit_project_and_the_files(self):
        argv = self.run_helper()
        self.assertEqual(
            argv[:5], ["compose", "-p", normalize(ROOT.name), "-f", "compose.yml"]
        )
        self.assertEqual(argv[-3:], ["ps", "-q", "infinito"])

    def test_named_call_passes_the_stack_name(self):
        argv = self.run_helper(INFINITO_STACK_NAME="demo")
        self.assertEqual(argv[:3], ["compose", "-p", "demo"])


class TestLoaderContainerNames(unittest.TestCase):
    DOTENV: ClassVar[dict[str, dict[str, str]]] = {
        "main": {
            "INFINITO_DISTRO": "debian",
            "INFINITO_CONTAINER": "infinito_nexus_debian",
            "INFINITO_RUNNER_PREFIX": "infinito",
            "INFINITO_STACK_NAME": "",
        },
        "worktree": {
            "INFINITO_DISTRO": "debian",
            "INFINITO_CONTAINER": "infinito_nexus_feature_iam_reqs_x",
            "INFINITO_RUNNER_PREFIX": "infinito-feature-iam-reqs-x",
            "INFINITO_STACK_NAME": "",
        },
    }

    def load(self, dotenv: dict[str, str], steps: str) -> dict[str, str]:
        checkout = scratch_dir(self)
        loader = checkout / "scripts" / "meta" / "env"
        loader.mkdir(parents=True)
        for name in ("load.sh", "python.sh"):
            shutil.copy(ROOT / "scripts" / "meta" / "env" / name, loader)
        (checkout / ".env").write_text(
            "".join(f"{k}={v}\n" for k, v in dotenv.items()), encoding="utf-8"
        )
        show = "printf '%s\\n' " + " ".join(f'"{k}=${{{k}:-}}"' for k in SHOWN)
        proc = subprocess.run(
            [
                "bash",
                "-c",
                f"load() {{ source scripts/meta/env/load.sh; }}\n{steps}\n{show}",
            ],
            env=clean_env(),
            cwd=checkout,
            capture_output=True,
            text=True,
            check=True,
        )
        return dict(line.split("=", 1) for line in proc.stdout.splitlines())

    def test_unnamed_main_checkout_keeps_the_dotenv_names(self):
        self.assertEqual(self.load(self.DOTENV["main"], "load"), self.DOTENV["main"])

    def test_unnamed_worktree_keeps_its_pinned_names(self):
        shown = self.load(self.DOTENV["worktree"], "load\nload")
        self.assertEqual(shown, self.DOTENV["worktree"])

    def test_a_named_stack_derives_its_container_names(self):
        shown = self.load(
            self.DOTENV["worktree"], "export INFINITO_STACK_NAME=demo-1\nload"
        )
        self.assertEqual(shown["INFINITO_CONTAINER"], "infinito_nexus_demo_1")
        self.assertEqual(shown["INFINITO_RUNNER_PREFIX"], "infinito-demo-1")

    def test_naming_a_stack_after_the_first_load_derives_its_names(self):
        shown = self.load(
            self.DOTENV["main"], "load\nexport INFINITO_STACK_NAME=demo\nload"
        )
        self.assertEqual(shown["INFINITO_CONTAINER"], "infinito_nexus_demo")

    def test_dropping_the_name_restores_the_dotenv_names(self):
        shown = self.load(
            self.DOTENV["worktree"],
            "export INFINITO_STACK_NAME=demo\nload\nexport INFINITO_STACK_NAME=\nload",
        )
        self.assertEqual(shown, self.DOTENV["worktree"])


if __name__ == "__main__":
    unittest.main()
