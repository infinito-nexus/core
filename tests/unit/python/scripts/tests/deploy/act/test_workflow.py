from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "act" / "workflow.sh"
ACT_STUB = '#!/usr/bin/env bash\nprintf "%s\\n" "$@" >"${STUB_LOG}"\n'
DB_ENV = "INFINITO_VULNERABILITY_DB_HOST_PATH"


def run_act(
    db_host_path: str | None,
) -> tuple[subprocess.CompletedProcess, list[str], Path, bool]:
    """Run the wrapper against an ``act`` stub that records its argv.

    Args:
        db_host_path: value of ``INFINITO_VULNERABILITY_DB_HOST_PATH`` below a
            scratch directory, or None to leave it unset.

    Returns:
        The finished process, the argv act received, the shared database
        directory the run was given, and whether it existed afterwards.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "act"
        stub.write_text(ACT_STUB)
        stub.chmod(0o755)
        log = Path(tmp) / "act.log"
        log.touch()
        workflow = Path(tmp) / "call-test-deploy.yml"
        workflow.write_text("on: workflow_dispatch\njobs: {}\n")
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("BASH_ENV", DB_ENV, "ACT_CONTAINER_OPTIONS")
        }
        env.update(
            PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            ACT_WORKFLOW=str(workflow),
            ACT_ACTION_CACHE_PATH=str(Path(tmp) / "actcache"),
            INFINITO_CONTAINER="infinito-test",
            ACT_PLATFORM_IMAGE="catthehacker/ubuntu:act-latest",
        )
        shared = Path(tmp) / "cache" / (db_host_path or "unset")
        if db_host_path is not None:
            env[DB_ENV] = str(shared)
        done = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        argv = log.read_text().splitlines()  # nocheck: cache-read  stub call log
        return done, argv, shared, shared.is_dir()


def option(argv: list[str], flag: str) -> list[str]:
    return [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == flag]


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


if __name__ == "__main__":
    unittest.main()
