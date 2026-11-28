"""The test, lint and lint-install wrappers run in the shared test runner infinito-test-<hash>."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.unit.python.scripts.image._checkout import (
    git,
    loaded_env,
    loaded_in,
    toolchain_checkout,
)

EXTRA = (
    "scripts/lint/diff/files.sh",
    "scripts/lint/python.sh",
    "scripts/lint/wrapper.sh",
    "scripts/meta/compose.sh",
    "scripts/tests/code/wrapper.sh",
    "scripts/tests/runner/down.sh",
    "scripts/tests/runner/lib.sh",
    "scripts/tests/runner/status.sh",
)
STATUS_SCRIPT = "scripts/tests/runner/status.sh"
RUNNER_CHANGES = ("docker run ", "docker start ", "docker rm ")
RUN_SCRIPT = "scripts/tests/code/run.sh"
STACK_FLAGS_MODULE = "cli.administration.deploy.development.stack"

DOCKER_STUB = """#!/usr/bin/env bash
printf 'docker %s\\n' "$*" >>"${STUB_LOG}"
case "$1" in
image)
\t[ -z "${STUB_IMAGE_MISSING:-}" ] || exit 1
\tprintf 'sha256:parent\\n'
\t;;
builder)
\t[ "$3" = "--help" ] && printf '      --max-used-space bytes\\n'
\t;;
inspect)
\t[ -n "${STUB_RUNNER_STATE:-}" ] || exit 1
\tcase "$*" in
\t*State.Running*) printf '%s\\n' "${STUB_RUNNER_STATE}" ;;
\t*Labels*) printf '%s\\n' "${STUB_RUNNER_ROOTS}" ;;
\tesac
\t;;
compose)
\tcase "$*" in *" ps -q infinito"*) printf '%s' "${STUB_COMPOSE_PS:-}" ;; esac
\t;;
esac
exit 0
"""

MAKE_STUB = """#!/usr/bin/env bash
printf 'make %s\\n' "$*" >>"${STUB_LOG}"
"""

PYTHON_SHIM = f"""#!/usr/bin/env bash
if [ "$1 $2 $3" = "-m cli.administration.infra attach" ]; then
\tprintf 'python %s\\n' "$*" >>"${{STUB_LOG}}"
\t[ -z "${{STUB_INFRA_NETWORK:-}}" ] || printf '%s\\n' "${{STUB_INFRA_NETWORK}}"
\texit 0
fi
if [ "$1 $2" = "-m {STACK_FLAGS_MODULE}" ]; then
\tprintf -- '-p\\n%s\\n-f\\ncompose.yml\\n' "${{INFINITO_STACK_NAME}}"
\texit 0
fi
exec {sys.executable} "$@"
"""


def _executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class TestWrapperSharedRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        _executable(cls.base / "bin" / "docker", DOCKER_STUB)
        _executable(cls.base / "bin" / "make", MAKE_STUB)
        _executable(cls.base / "venv" / "bin" / "python", PYTHON_SHIM)
        cls.home = cls.base / "home"
        cls.worktrees = cls.home / ".local" / "share" / "worktrees"
        cls.worktrees.mkdir(parents=True)
        cls.primary = toolchain_checkout(cls.base, EXTRA)
        cls.linked = cls.worktrees / "feature"
        git(cls.primary, "worktree", "add", "--quiet", "--detach", str(cls.linked))
        cls.outside = cls.base / "elsewhere"
        git(cls.primary, "worktree", "add", "--quiet", "--detach", str(cls.outside))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _run(
        self, checkout: Path, script: str, *args: str, **overrides: str
    ) -> tuple[subprocess.CompletedProcess, list[str]]:
        env = loaded_env(
            self.base,
            HOME=str(self.home),
            MAKE=str(self.base / "bin" / "make"),
            INFINITO_VENV_DIR=str(self.base / "venv"),
            INFINITO_DOCKER_MOUNT="/var/lib/docker",
            INFINITO_WAIT_HEALTH_TIMEOUT_S="600",
            INFINITO_TEST_PATTERN="test*.py",
            INFINITO_TEST_RUNNER="docker",
            INFINITO_TEST_TYPE="unit",
            INFINITO_LINT_RUNNER="docker",
        )
        env.update(overrides)
        log = Path(env["STUB_LOG"])
        log.unlink(missing_ok=True)
        done = subprocess.run(
            ["bash", str(checkout / script), *args],
            cwd=checkout,
            env=loaded_in(checkout, env),
            capture_output=True,
            text=True,
            check=False,
        )
        if not log.exists():
            return done, []
        return done, log.read_text().splitlines()  # nocheck: cache-read  stub call log

    def _test_run(self, checkout: Path, **overrides: str):
        return self._run(
            checkout, "scripts/tests/code/wrapper.sh", RUN_SCRIPT, **overrides
        )

    @staticmethod
    def _runner_exec(calls: list[str]) -> str:
        execs = [call for call in calls if call.startswith("docker exec --workdir ")]
        if len(execs) != 1:
            raise AssertionError(f"expected one runner exec, got {calls}")
        return execs[0]

    @staticmethod
    def _tmpdir(checkout: Path) -> str:
        digest = hashlib.sha256(str(checkout).encode()).hexdigest()[:16]
        return f"/tmp/infinito-test/{digest}"

    def test_the_test_run_execs_in_the_runner_with_the_checkout_as_workdir(
        self,
    ) -> None:
        done, calls = self._test_run(self.primary)
        self.assertEqual(done.returncode, 0, done.stderr)
        call = self._runner_exec(calls)
        self.assertIn(f"--workdir {self.primary} ", call)
        self.assertIn(f"-e INFINITO_SRC_DIR={self.primary} ", call)
        self.assertIn(f"-e TMPDIR={self._tmpdir(self.primary)} ", call)
        self.assertIn(f"-e BASH_ENV={self.primary}/scripts/meta/env/load.sh ", call)
        self.assertRegex(call, r" infinito-test-[0-9a-f]{16} bash --login ")
        self.assertTrue(
            call.endswith(f"bash --login {self.primary}/{RUN_SCRIPT}"), call
        )

    def test_the_test_run_never_starts_a_deploy_stack(self) -> None:
        _, calls = self._test_run(self.primary)
        self.assertFalse([call for call in calls if call.startswith("make ")], calls)
        self.assertFalse(
            [call for call in calls if call.startswith("docker compose")], calls
        )

    def test_the_runner_mounts_the_primary_checkout_and_the_worktree_root(self) -> None:
        _, calls = self._test_run(self.primary)
        run = next(call for call in calls if call.startswith("docker run "))
        self.assertIn(f"-v {self.primary}:{self.primary} ", run)
        self.assertIn(f"-v {self.worktrees}:{self.worktrees} ", run)
        self.assertIn(
            f"nexus.infinito.worktree-roots={self.primary}:{self.worktrees} ", run
        )
        self.assertIn(" --privileged ", run)
        self.assertTrue(
            [
                call
                for call in calls
                if call.startswith("docker exec ")
                and " timeout 600 systemctl is-system-running --wait" in call
            ],
            calls,
        )

    def test_the_runner_joins_the_infra_network_attach_names(self) -> None:
        _done, calls = self._test_run(self.primary, STUB_INFRA_NETWORK="infinito-infra")
        run = next(call for call in calls if call.startswith("docker run "))
        self.assertIn("--network infinito-infra", run)
        self.assertIn("python -m cli.administration.infra attach", calls)

    def test_without_an_attached_network_the_runner_joins_none(self) -> None:
        _done, calls = self._test_run(self.primary, STUB_INFRA_NETWORK="")
        run = next(call for call in calls if call.startswith("docker run "))
        self.assertNotIn("--network", run)

    def test_the_worktree_roots_override_replaces_the_default_mounts(self) -> None:
        roots = f"{self.primary}:{self.outside}"
        _, calls = self._test_run(self.outside, INFINITO_WORKTREE_ROOTS=roots)
        run = next(call for call in calls if call.startswith("docker run "))
        self.assertIn(f"-v {self.outside}:{self.outside} ", run)
        self.assertNotIn(str(self.worktrees), run)
        self.assertIn(f"--workdir {self.outside} ", self._runner_exec(calls))

    def test_two_checkouts_share_the_runner_with_their_own_workdir_and_tmpdir(
        self,
    ) -> None:
        _, primary_calls = self._test_run(self.primary)
        _, linked_calls = self._test_run(self.linked)
        primary_exec = self._runner_exec(primary_calls)
        linked_exec = self._runner_exec(linked_calls)
        name = primary_exec.split(" bash --login ")[0].rsplit(" ", 1)[1]
        self.assertIn(f" {name} bash --login ", linked_exec)
        self.assertIn(f"--workdir {self.linked} ", linked_exec)
        self.assertIn(f"-e TMPDIR={self._tmpdir(self.linked)} ", linked_exec)
        self.assertNotEqual(self._tmpdir(self.linked), self._tmpdir(self.primary))

    def test_a_missing_image_is_built_for_the_image_source_dir(self) -> None:
        done, calls = self._test_run(self.linked, STUB_IMAGE_MISSING="1")
        self.assertEqual(done.returncode, 0, done.stderr)
        build = next(call for call in calls if call.startswith("docker build "))
        self.assertIn("--build-arg INFINITO_SRC_DIR=/opt/src/infinito ", build)
        self.assertIn("--target toolchain", build)
        self.assertLess(
            calls.index(build),
            calls.index(next(c for c in calls if c.startswith("docker run "))),
        )

    def test_a_running_runner_is_reused(self) -> None:
        _, calls = self._test_run(
            self.linked,
            STUB_RUNNER_STATE="true",
            STUB_RUNNER_ROOTS=f"{self.primary}:{self.worktrees}",
        )
        self.assertFalse([call for call in calls if call.startswith("docker run ")])
        self.assertIn(f"--workdir {self.linked} ", self._runner_exec(calls))

    def test_a_checkout_outside_the_roots_is_refused(self) -> None:
        done, calls = self._test_run(self.outside)
        self.assertEqual(done.returncode, 2)
        self.assertIn(str(self.outside), done.stderr)
        self.assertIn(str(self.primary), done.stderr)
        self.assertIn(str(self.worktrees), done.stderr)
        self.assertIn("make test-runner-down", done.stderr)
        self.assertFalse(
            [call for call in calls if call.startswith(("docker run", "docker exec"))]
        )

    def test_a_running_runner_refuses_a_checkout_outside_its_mounts(self) -> None:
        done, calls = self._test_run(
            self.linked,
            STUB_RUNNER_STATE="true",
            STUB_RUNNER_ROOTS=str(self.primary),
        )
        self.assertEqual(done.returncode, 2)
        self.assertIn(f"({self.primary})", done.stderr)
        self.assertFalse([call for call in calls if call.startswith("docker exec")])

    def test_the_lint_wrapper_execs_in_the_same_runner(self) -> None:
        _, test_calls = self._test_run(self.linked)
        done, calls = self._run(self.linked, "scripts/lint/wrapper.sh", "python")
        self.assertEqual(done.returncode, 0, done.stderr)
        call = self._runner_exec(calls)
        name = (
            self._runner_exec(test_calls).split(" bash --login ")[0].rsplit(" ", 1)[1]
        )
        self.assertIn(f" {name} bash {self.linked}/scripts/lint/python.sh", call)
        self.assertIn(f"--workdir {self.linked} ", call)
        self.assertIn("-e LINT_DIFF_FILES= ", call)

    def test_the_lint_install_wrapper_execs_in_the_same_runner(self) -> None:
        done, calls = self._run(self.primary, "scripts/install/wrapper.sh")
        self.assertEqual(done.returncode, 0, done.stderr)
        call = self._runner_exec(calls)
        self.assertRegex(
            call, r" infinito-test-[0-9a-f]{16} python3 -m utils\.install\.lint$"
        )
        self.assertFalse([call for call in calls if call.startswith("make ")])

    def test_runner_down_removes_the_runner_of_the_checkouts_image(self) -> None:
        _, test_calls = self._test_run(self.linked)
        name = (
            self._runner_exec(test_calls).split(" bash --login ")[0].rsplit(" ", 1)[1]
        )
        done, calls = self._run(
            self.linked, "scripts/tests/runner/down.sh", STUB_RUNNER_STATE="true"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"docker rm -f -v {name}", calls)

    def _runner_name(self) -> str:
        _, test_calls = self._test_run(self.linked)
        return (
            self._runner_exec(test_calls).split(" bash --login ")[0].rsplit(" ", 1)[1]
        )

    def test_runner_status_shows_the_runner_of_the_checkouts_image(self) -> None:
        name = self._runner_name()
        done, calls = self._run(
            self.linked,
            STATUS_SCRIPT,
            STUB_RUNNER_STATE="true",
            STUB_RUNNER_ROOTS=f"{self.primary}:{self.worktrees}",
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"Shared test runner {name} from ", done.stdout)
        self.assertIn("running=true", done.stdout)
        self.assertIn(f"worktree roots {self.primary}:{self.worktrees}", done.stdout)
        self.assertFalse([call for call in calls if call.startswith(RUNNER_CHANGES)])

    def test_runner_status_without_a_runner_starts_none(self) -> None:
        name = self._runner_name()
        done, calls = self._run(self.linked, STATUS_SCRIPT)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"No shared test runner {name} exists", done.stdout)
        self.assertNotIn("running=", done.stdout)
        self.assertFalse([call for call in calls if call.startswith(RUNNER_CHANGES)])

    def test_a_named_stack_runs_the_tests_in_its_own_container(self) -> None:
        done, calls = self._test_run(
            self.primary,
            INFINITO_STACK_NAME="probe",
            INFINITO_ENV_LOADED_STACK="probe",
            STUB_COMPOSE_PS="abc123",
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        execs = [call for call in calls if " exec -T " in call]
        self.assertEqual(len(execs), 1, calls)
        self.assertTrue(
            execs[0].startswith("docker compose -p probe -f compose.yml exec -T ")
        )
        self.assertIn("--workdir /opt/src/infinito infinito bash --login ", execs[0])
        self.assertFalse([call for call in calls if "infinito-test-" in call])

    def test_a_named_stack_runs_the_lints_in_its_own_container(self) -> None:
        done, calls = self._run(
            self.primary,
            "scripts/lint/wrapper.sh",
            "python",
            INFINITO_STACK_NAME="probe",
            INFINITO_ENV_LOADED_STACK="probe",
            STUB_COMPOSE_PS="abc123",
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        execs = [call for call in calls if " exec -T " in call]
        self.assertEqual(len(execs), 1, calls)
        self.assertTrue(
            execs[0].startswith("docker compose -p probe -f compose.yml exec -T ")
        )
        self.assertFalse([call for call in calls if "infinito-test-" in call])


if __name__ == "__main__":
    unittest.main()
