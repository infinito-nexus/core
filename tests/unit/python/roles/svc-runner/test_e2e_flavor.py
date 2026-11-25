from __future__ import annotations

import importlib
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.env.parser import CUSTOM_ENV, custom_env_value

render = importlib.import_module("tests.unit.python.roles.svc-runner._render")

SUITE = render.ROLE / "files" / "test"
EXTERNAL_MARK = "EXTERNAL RAN"
CACHE_KEY = "INFINITO_CACHE_STACK"
CACHE_PIN = f"{CACHE_KEY}=false"


def _executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)
    return path


class _Suite(unittest.TestCase):
    flavor = "github"

    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.stage = self.root / "stage"
        self.stage.mkdir()
        shutil.copy(SUITE / "test.sh", self.stage / "test.sh")
        shutil.copy(SUITE / "local.sh", self.stage / "local.sh")
        _executable(self.stage / "external.sh", f'echo "{EXTERNAL_MARK}"')
        self.log = self.root / "container.log"
        self.missing = self.root / "missing"
        self.missing.write_text("")
        stubs = self.root / "bin"
        _executable(
            stubs / "container",
            f'printf "%s\\n" "$*" >> "{self.log}"\n'
            'if [[ "$1" == "inspect" ]]; then echo running; exit 0; fi\n'
            'if [[ "$1" == "exec" && "$3" == "test" && "$4" == "-d" ]]; then\n'
            f'    if grep -qxF -- "$5" "{self.missing}"; then exit 1; fi\n'
            "fi\n"
            "exit 0",
        )
        _executable(stubs / "docker", "exit 0")
        self.install = self.root / "install"
        self.env = {
            "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.root),
            **render.env_values(render.render(render.TEST_ENV, self.flavor)),
            "RUNNER_INSTALL_DIR": str(self.install),
        }

    def run_suite(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.stage / "test.sh")],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def calls(self) -> list[str]:
        return read_text(str(self.log)).splitlines() if self.log.is_file() else []

    def root_probes(self) -> list[str]:
        return [
            call
            for call in self.calls()
            if call.startswith("exec ")
            and call.endswith(tuple(f"test -d {root}" for root in render.ROOTS))
        ]


class TestLocalFlavorSuite(_Suite):
    flavor = "local"

    def test_the_rendered_env_selects_the_local_branch(self) -> None:
        self.assertEqual(self.env["RUNNER_FLAVOR"], "local")
        self.assertEqual(self.env["RUNNER_WORKTREE_ROOTS"], ":".join(render.ROOTS))
        self.assertNotIn("RUNNER_GIT_REF", self.env)

    def test_the_suite_probes_the_checkout_the_role_default_names(self) -> None:
        self.assertEqual(self.env["RUNNER_SRC_DIR"], render.SRC_DIR)
        run = self.run_suite()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"exec runner-1 test -d {render.SRC_DIR}", self.calls())

    def test_the_suite_passes_without_github_inputs(self) -> None:
        run = self.run_suite()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ALL CHECKS PASSED", run.stdout)
        self.assertNotIn(EXTERNAL_MARK, run.stdout)
        self.assertEqual([call for call in self.calls() if call.startswith("cp ")], [])
        self.assertEqual(
            sorted(self.root_probes()),
            sorted(
                f"exec runner-{index} test -d {root}"
                for index in (1, 2)
                for root in render.ROOTS
            ),
        )

    def test_the_suite_without_the_flavor_dispatch_aborts(self) -> None:
        del self.env["RUNNER_FLAVOR"]
        run = self.run_suite()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("RUNNER_GIT_REF", run.stderr)

    def test_a_root_missing_in_a_runner_fails(self) -> None:
        self.missing.write_text(f"{render.ROOTS[1]}\n")
        run = self.run_suite()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(f"FAIL: worktree root {render.ROOTS[1]}", run.stdout)

    def test_a_checkout_outside_the_roots_fails(self) -> None:
        self.missing.write_text(f"{self.env['RUNNER_SRC_DIR']}\n")
        run = self.run_suite()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("lies outside the worktree roots", run.stdout)


class TestGithubFlavorSuite(_Suite):
    flavor = "github"

    def test_the_suite_copies_the_checkout_and_runs_external(self) -> None:
        _executable(self.install / "1" / "run.sh", "exit 0")
        run = self.run_suite()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(EXTERNAL_MARK, run.stdout)
        src = self.env["RUNNER_SRC_DIR"]
        self.assertEqual(
            [call for call in self.calls() if call.startswith("cp ")],
            [f"cp {src}/. runner-1:{src}"],
        )
        self.assertEqual(self.root_probes(), [])

    def test_a_missing_runner_binary_fails(self) -> None:
        run = self.run_suite()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("runner binary absent", run.stdout)


class TestNestedCacheStackGithub(_Suite):
    flavor = "github"

    def setUp(self) -> None:
        super().setUp()
        stubs = self.root / "bin"
        base = stubs / "container-base"
        (stubs / "container").rename(base)
        _executable(
            stubs / "container",
            'if [[ "$1 $2 $3 $5 $6" == "exec --user root bash -c" ]]; then\n'
            f'    printf "%s\\n" "$*" >> "{self.log}"\n'
            '    exec bash -c "$7"\n'
            "fi\n"
            f'exec "{base}" "$@"',
        )
        self.copied = self.root / "copied.env"
        _executable(
            stubs / "tar",
            'if [[ "$3" == "-xf" ]]; then\n'
            "    cat >/dev/null\n"
            f'    if [[ -e "{self.copied}" || -L "{self.copied}" ]]; then\n'
            f'        cp -P "{self.copied}" "$2/{CUSTOM_ENV}"\n'
            "    fi\n"
            "fi\n"
            "exit 0",
        )
        _executable(stubs / "chown", "exit 0")
        _executable(self.install / "1" / "run.sh", "exit 0")
        self.nested = self.install / "1" / "nested-src"

    def deploy(self) -> None:
        run = self.run_suite()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_the_nested_copy_turns_the_cache_stack_off(self) -> None:
        self.deploy()
        self.assertEqual(custom_env_value(self.nested, CACHE_KEY), "false")
        mode = (self.nested / CUSTOM_ENV).stat().st_mode
        self.assertEqual(stat.S_IMODE(mode), 0o600)

    def test_the_pin_overrides_a_copied_custom_env_without_a_final_newline(
        self,
    ) -> None:
        self.copied.write_text(f"INFINITO_DISTRO=arch\n{CACHE_KEY}=true")
        self.deploy()
        self.assertEqual(custom_env_value(self.nested, CACHE_KEY), "false")
        self.assertEqual(custom_env_value(self.nested, "INFINITO_DISTRO"), "arch")

    def test_the_pin_replaces_a_copied_link_instead_of_its_target(self) -> None:
        target = self.root / "target.env"
        target.write_text(f"{CACHE_KEY}=true\n")
        self.copied.symlink_to(target)
        self.deploy()
        self.assertFalse((self.nested / CUSTOM_ENV).is_symlink())
        self.assertEqual(read_text(str(target)), f"{CACHE_KEY}=true\n")
        self.assertEqual(custom_env_value(self.nested, CACHE_KEY), "false")

    def test_the_pin_lands_before_the_nested_install(self) -> None:
        self.deploy()
        calls = self.calls()
        pin = next(index for index, call in enumerate(calls) if CACHE_PIN in call)
        install = next(
            index for index, call in enumerate(calls) if "make install" in call
        )
        self.assertLess(pin, install)

    def test_without_the_pin_the_copy_keeps_the_cache_stack_on(self) -> None:
        script = self.stage / "local.sh"
        source = read_text(str(script))
        self.assertIn(CACHE_PIN, source)
        script.write_text(source.replace(CACHE_PIN, "INFINITO_CACHE_UNPINNED=false"))
        self.copied.write_text(f"{CACHE_KEY}=true\n")
        self.deploy()
        self.assertEqual(custom_env_value(self.nested, CACHE_KEY), "true")


class TestNestedCacheStackLocal(TestNestedCacheStackGithub):
    flavor = "local"


if __name__ == "__main__":
    unittest.main()
