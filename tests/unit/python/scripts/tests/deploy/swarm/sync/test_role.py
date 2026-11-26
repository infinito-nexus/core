"""swarm/sync/role.sh refuses without a kept cluster and otherwise runs the role
sync inside the act job container of its own worktree."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.utils.make_target import run_target
from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "swarm" / "sync" / "role.sh"
ROLE_SH = "scripts/tests/deploy/swarm/sync/role.sh"
SYNCED = f"{ROLE_SH} app=web-app-demo"
MANAGER = "demo-swarm-mgr-01"
DOCKER_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "$*" >>"${STUB_LOG}"\n'
    'case "$1" in\n'
    "inspect)\n"
    '  [ "${STUB_RUNNING}" != missing ] || exit 1\n'
    '  echo "${STUB_RUNNING}"\n'
    "  ;;\n"
    "ps)\n"
    '  case "$*" in *"label=infinito.worktree=own"*)\n'
    '    for id in ${STUB_ACT_IDS}; do echo "${id}"; done ;;\n'
    "  esac\n"
    "  ;;\n"
    'exec) exit "${STUB_EXEC_RC}" ;;\n'
    "esac\n"
)
_SCRIPT_KEYS = ("BASH_ENV", "INFINITO_CONTAINER", "app", "variant", "SWARM_NAME")


def sync(
    overrides: dict[str, str | None] | None = None,
    *,
    running: str = "true",
    act_ids: str = "act-1",
    exec_rc: int = 0,
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run role.sh against a ``docker`` stub.

    Args:
        overrides: environment entries to set, or to drop when the value is None.
        running: what ``docker inspect`` reports for the manager; ``missing``
            makes it fail like an absent container.
        act_ids: space-separated act job container ids ``docker ps`` lists for
            the label ``infinito.worktree=own``.
        exec_rc: exit code of the stub ``docker exec``.

    Returns:
        The finished process and every docker invocation in order.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "docker"
        stub.write_text(DOCKER_STUB)
        stub.chmod(0o755)
        log = Path(tmp) / "docker.log"
        log.touch()
        env = {k: v for k, v in os.environ.items() if k not in _SCRIPT_KEYS}
        env.update(
            PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            STUB_RUNNING=running,
            STUB_ACT_IDS=act_ids,
            STUB_EXEC_RC=str(exec_rc),
            INFINITO_CONTAINER="own",
            INFINITO_SWARM_MGR_NAME="swarm-mgr-01",
            app="web-app-demo",
            SWARM_NAME="demo",
            variant="0",
        )
        for key, value in (overrides or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        done = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return done, log.read_text().splitlines()  # nocheck: cache-read  stub call log


def _calls(calls: list[str], verb: str) -> list[str]:
    return [call for call in calls if call.split(" ", 1)[0] == verb]


class TestKeptCluster(unittest.TestCase):
    def test_the_sync_runs_inside_the_act_job_container(self) -> None:
        done, calls = sync()
        self.assertEqual(done.returncode, 0, done.stderr)
        (exec_call,) = _calls(calls, "exec")
        self.assertTrue(exec_call.startswith(f"exec -i -w {PROJECT_ROOT} "), exec_call)
        self.assertIn(" act-1 ", exec_call)
        self.assertIn("APP=web-app-demo", exec_call)
        self.assertIn("VARIANT=0", exec_call)
        self.assertIn("source scripts/meta/env/load.sh", exec_call)
        self.assertIn("-m utils.tests.swarm.sync", exec_call)

    def test_the_manager_of_the_named_cluster_is_probed(self) -> None:
        _, calls = sync()
        (inspect_call,) = _calls(calls, "inspect")
        self.assertTrue(inspect_call.endswith(f" {MANAGER}"), inspect_call)

    def test_only_the_own_worktrees_act_job_containers_are_listed(self) -> None:
        _, calls = sync()
        (ps_call,) = _calls(calls, "ps")
        self.assertIn("name=^act-", ps_call)
        self.assertIn("label=infinito.worktree=own", ps_call)
        self.assertNotIn(" -a", ps_call)

    def test_the_sync_exit_code_is_the_scripts_exit_code(self) -> None:
        done, _ = sync(exec_rc=4)
        self.assertEqual(done.returncode, 4)


class TestRefusals(unittest.TestCase):
    def test_a_stopped_manager_refuses_before_the_act_container_is_looked_up(
        self,
    ) -> None:
        done, calls = sync(running="false")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(_calls(calls, "ps") + _calls(calls, "exec"), [])
        self.assertIn(MANAGER, done.stderr)
        self.assertIn("make swarm-zombie app=web-app-demo keep=true", done.stderr)

    def test_an_absent_manager_refuses(self) -> None:
        done, calls = sync(running="missing")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(_calls(calls, "exec"), [])
        self.assertIn(MANAGER, done.stderr)

    def test_no_act_job_container_refuses(self) -> None:
        done, calls = sync(act_ids="")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(_calls(calls, "exec"), [])
        self.assertIn("infinito.worktree=own", done.stderr)
        self.assertIn("keep=true", done.stderr)

    def test_a_foreign_worktrees_act_job_container_is_not_used(self) -> None:
        done, calls = sync({"INFINITO_CONTAINER": "foreign"})
        self.assertEqual(done.returncode, 1)
        self.assertEqual(_calls(calls, "exec"), [])

    def test_two_act_job_containers_refuse_instead_of_guessing(self) -> None:
        done, calls = sync(act_ids="act-1 act-2")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(_calls(calls, "exec"), [])
        self.assertIn("act-1", done.stderr)
        self.assertIn("act-2", done.stderr)

    def test_malformed_or_missing_arguments_run_nothing(self) -> None:
        for overrides in (
            {"app": None},
            {"app": "web-app-demo; id"},
            {"app": "-l"},
            {"variant": None},
            {"variant": "1a"},
            {"SWARM_NAME": None},
            {"INFINITO_CONTAINER": None},
        ):
            with self.subTest(overrides=overrides):
                done, calls = sync(overrides)
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(calls, [])


class TestSwarmRoleSyncWiring(unittest.TestCase):
    def _target(self, *arguments: str) -> list[str]:
        done, calls = run_target(
            "swarm-role-sync",
            ("app=web-app-demo", *arguments),
            (ROLE_SH,),
            {"STUB_ENV": "app SWARM_NAME variant"},
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return calls

    def test_the_target_names_the_cluster_like_swarm_zombie(self) -> None:
        for arguments, cluster, variant in (
            ((), "web-app-demo", "0"),
            (("name=demo", "variant=2"), "demo", "2"),
        ):
            with self.subTest(arguments=arguments):
                synced = f"{SYNCED} SWARM_NAME={cluster} variant={variant}"
                self.assertEqual(self._target(*arguments), [synced])

    def test_pw_reruns_the_spec_through_swarm_playwright_after_the_sync(self) -> None:
        rerun = "make swarm-playwright role=web-app-demo name=web-app-demo"
        self.assertEqual(
            self._target("pw=--grep design"),
            [
                f"{SYNCED} SWARM_NAME=web-app-demo variant=0",
                f"{rerun} pw=--grep\\ design",
            ],
        )


if __name__ == "__main__":
    unittest.main()
