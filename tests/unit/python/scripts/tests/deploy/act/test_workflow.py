from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cli.meta.env.__main__ import HOST_OWNED_KEY
from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "act" / "workflow.sh"
ACT_STUB = '#!/usr/bin/env bash\nprintf \'%s\\0\' "$@" >"${STUB_LOG}"\n'
DB_ENV = "INFINITO_VULNERABILITY_DB_HOST_PATH"
HOST_OWNED = f"{HOST_OWNED_KEY}=true"
EXTRA_VARS = json.dumps(
    {
        "applications": {
            "web-app-erpnext": {"services": {"erpnext": {"server_scripts": True}}},
            "web-app-cst-demo": {"billing": {"bank": "Verify Bank, IBAN DE00 0000"}},
        }
    }
)


def run_act(
    db_host_path: str | None,
    act_env: str = "",
    *,
    act_bind: str | None = None,
    custom_role: bool = False,
) -> tuple[subprocess.CompletedProcess, list[str], Path, bool]:
    """Run the wrapper against an ``act`` stub that records its argv.

    Args:
        db_host_path: value of ``INFINITO_VULNERABILITY_DB_HOST_PATH`` below a
            scratch directory, or None to leave it unset.
        act_env: value of ``ACT_ENV``.
        act_bind: value of ``ACT_BIND``, or None to leave it unset.
        custom_role: run the wrapper from a scratch checkout that holds a
            pulled ``roles/web-app-cst-*`` role instead of this repository.

    Returns:
        The finished process, the argv act received (one list item per
        argument), the shared database directory the run was given, and
        whether it existed afterwards.
    """
    with tempfile.TemporaryDirectory() as tmp:
        script = SCRIPT
        if custom_role:
            root = Path(tmp) / "repo"
            (root / "roles" / "web-app-cst-demo").mkdir(parents=True)
            (root / ".github" / "workflows").mkdir(parents=True)
            script = root / "scripts" / "tests" / "deploy" / "act" / "workflow.sh"
            script.parent.mkdir(parents=True)
            script.symlink_to(SCRIPT)
        stub = Path(tmp) / "act"
        stub.write_text(ACT_STUB)
        stub.chmod(0o755)
        log = Path(tmp) / "act.argv"
        log.touch()
        workflow = Path(tmp) / "call-test-deploy.yml"
        workflow.write_text("on: workflow_dispatch\njobs: {}\n")
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("BASH_ENV", DB_ENV, "ACT_CONTAINER_OPTIONS", "ACT_BIND")
        }
        if act_bind is not None:
            env["ACT_BIND"] = act_bind
        env.update(
            PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            ACT_WORKFLOW=str(workflow),
            ACT_ENV=act_env,
            ACT_ACTION_CACHE_PATH=str(Path(tmp) / "actcache"),
            INFINITO_CONTAINER="infinito-test",
            ACT_PLATFORM_IMAGE="catthehacker/ubuntu:act-latest",
        )
        shared = Path(tmp) / "cache" / (db_host_path or "unset")
        if db_host_path is not None:
            env[DB_ENV] = str(shared)
        done = subprocess.run(
            ["bash", str(script)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        argv = log.read_text().split("\0")[:-1]  # nocheck: cache-read  stub argv log
        return done, argv, shared, shared.is_dir()


def act_argv(act_env: str) -> list[str]:
    """Run the act wrapper and return the argv the stub got.

    Args:
        act_env: value of ``ACT_ENV``.

    Returns:
        The arguments the stub received, one list item per argument.
    """
    done, argv, _shared, _created = run_act("vulnerability-db", act_env)
    done.check_returncode()
    return argv


def option(argv: list[str], flag: str) -> list[str]:
    return [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == flag]


def env_items(argv: list[str]) -> list[str]:
    """Collect the ``ACT_ENV`` values passed behind each ``--env`` flag.

    Args:
        argv: arguments the act stub received.

    Returns:
        Every ``--env`` value in order, without the wrapper's own
        ``INFINITO_VULNERABILITY_DB_HOST_PATH`` and host-owned ``.env`` pins.
    """
    return [
        value
        for value in option(argv, "--env")
        if not value.startswith(f"{DB_ENV}=") and value != HOST_OWNED
    ]


class TestVulnerabilityDatabaseBind(unittest.TestCase):
    def test_the_shared_databases_sit_at_the_host_path_in_the_job_container(
        self,
    ) -> None:
        done, argv, shared, _created = run_act("vulnerability-db")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(
            f"--volume {shared}:{shared}", option(argv, "--container-options")[0]
        )

    def test_the_job_steps_receive_the_host_path(self) -> None:
        _done, argv, shared, _created = run_act("vulnerability-db")
        self.assertIn(f"{DB_ENV}={shared}", option(argv, "--env"))

    def test_the_directory_exists_before_act_binds_it(self) -> None:
        _done, _argv, _shared, created = run_act("vulnerability-db")
        self.assertTrue(created)

    def test_the_job_container_keeps_the_host_daemon_socket(self) -> None:
        _done, argv, _shared, _created = run_act("vulnerability-db")
        self.assertNotIn("--container-daemon-socket", argv)

    def test_the_default_options_survive(self) -> None:
        _done, argv, _shared, _created = run_act("vulnerability-db")
        self.assertTrue(
            option(argv, "--container-options")[0].startswith(
                "--privileged --label infinito.worktree=infinito-test "
            )
        )

    def test_an_unset_host_path_starts_no_act_run(self) -> None:
        done, argv, _shared, created = run_act(None)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual((argv, created), ([], False))


class TestActWorkflowEnv(unittest.TestCase):
    def test_json_with_spaces_reaches_act_as_one_env_item(self) -> None:
        items = env_items(
            act_argv(
                "INFINITO_DEPLOY_MODE=swarm; "
                f"INFINITO_INVENTORY_EXTRA_VARS={EXTRA_VARS}; "
                "disable=matomo"
            )
        )
        self.assertEqual(
            items,
            [
                "INFINITO_DEPLOY_MODE=swarm",
                f"INFINITO_INVENTORY_EXTRA_VARS={EXTRA_VARS}",
                "disable=matomo",
            ],
        )

    def test_an_empty_value_still_passes_as_its_own_item(self) -> None:
        items = env_items(act_argv("INFINITO_INVENTORY_EXTRA_VARS=; disable=css"))
        self.assertEqual(items, ["INFINITO_INVENTORY_EXTRA_VARS=", "disable=css"])


class TestBoundCheckoutKeepsTheHostDotenv(unittest.TestCase):
    def test_an_explicit_bind_keeps_the_host_dotenv(self) -> None:
        done, argv, _shared, _created = run_act("vulnerability-db", act_bind="true")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--bind", argv)
        self.assertIn(HOST_OWNED, option(argv, "--env"))

    def test_a_bind_for_pulled_custom_roles_keeps_the_host_dotenv(self) -> None:
        done, argv, _shared, _created = run_act("vulnerability-db", custom_role=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--bind", argv)
        self.assertIn(HOST_OWNED, option(argv, "--env"))

    def test_the_marker_travels_only_with_the_bind(self) -> None:
        done, argv, _shared, _created = run_act("vulnerability-db", act_bind="false")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual("--bind" in argv, HOST_OWNED in option(argv, "--env"))


if __name__ == "__main__":
    unittest.main()
