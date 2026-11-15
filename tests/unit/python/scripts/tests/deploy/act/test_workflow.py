from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "act" / "workflow.sh"
SHARED = "INFINITO_CACHE_SHARED_HOST_PATH"
SHARED_PATH = "/var/cache/infinito/core/cache/shared"
DB_ENV = "INFINITO_VULNERABILITY_DB_HOST_PATH"
DB_PATH = "vulnerability-db"
ACT_STUB = (
    "#!/usr/bin/env bash\n"
    'printf \'%s\\0\' "$@" >"${STUB_LOG}"\n'
    'while [ "$#" -gt 0 ]; do\n'
    '\tif [ "$1" = -W ]; then cp "$2" "${STUB_WORKFLOW}"; fi\n'
    "\tshift\n"
    "done\n"
)
INFRA = "-m cli.administration.infra"
FRONTEND = "stub-package-cache-frontend"
PYTHON_STUB = (
    "#!/usr/bin/env bash\n"
    'case "$*" in\n'
    f'"{INFRA} cache-name frontend") echo {FRONTEND} ;;\n'
    f'"{INFRA} docker inspect {FRONTEND}") [ -n "${{STUB_FRONTEND}}" ] ;;\n'
    "*) exit 1 ;;\n"
    "esac\n"
)
WORKFLOW = """on: workflow_dispatch
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: pyproject.toml
      - uses: actions/setup-node@v6
        with:
          cache: npm
"""
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
    shared_cache: str = "",
    frontend: bool = True,
) -> tuple[subprocess.CompletedProcess, list[str], Path, bool, str]:
    """Run the act wrapper against ``act`` and infra CLI (``PYTHON``) stubs.

    Args:
        db_host_path: value of ``INFINITO_VULNERABILITY_DB_HOST_PATH`` below a
            scratch directory, or None to leave it unset.
        act_env: value of ``ACT_ENV``.
        shared_cache: value of ``INFINITO_CACHE_SHARED_HOST_PATH``; empty
            stands for a checkout without the shared cache folder.
        frontend: whether the package-cache frontend container exists.

    Returns:
        The finished process, the argv act received (one list item per
        argument), the shared database directory the run was given, whether
        it existed afterwards, and the workflow file the wrapper handed act
        (empty when act never ran).
    """
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in (("act", ACT_STUB), ("python-stub", PYTHON_STUB)):
            stub = Path(tmp) / name
            stub.write_text(body)
            stub.chmod(0o755)
        workflow = Path(tmp) / "call-test-deploy.yml"
        workflow.write_text(WORKFLOW)
        log = Path(tmp) / "act.argv"
        log.touch()
        handed = Path(tmp) / "act.workflow"
        handed.touch()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("BASH_ENV", SHARED, DB_ENV, "ACT_CONTAINER_OPTIONS")
        }
        if shared_cache:
            env[SHARED] = shared_cache
        env.update(
            PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            STUB_WORKFLOW=str(handed),
            STUB_FRONTEND="1" if frontend else "",
            PYTHON=str(Path(tmp) / "python-stub"),
            ACT_WORKFLOW=str(workflow),
            ACT_ENV=act_env,
            ACT_ACTION_CACHE_PATH=str(Path(tmp) / "actcache"),
            ACT_PLATFORM_IMAGE="catthehacker/ubuntu:act-latest",
            INFINITO_CONTAINER="infinito-test",
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
        argv = log.read_text().split("\0")[:-1]  # nocheck: cache-read  stub argv log
        copy = handed.read_text()  # nocheck: cache-read  stub workflow copy
        return done, argv, shared, shared.is_dir(), copy


def act_run(
    act_env: str, shared_cache: str = "", frontend: bool = True
) -> tuple[list[str], str]:
    """Run the act wrapper with the vulnerability databases pinned.

    Args:
        act_env: value of ``ACT_ENV``.
        shared_cache: value of ``INFINITO_CACHE_SHARED_HOST_PATH``.
        frontend: whether the package-cache frontend container exists.

    Returns:
        The arguments the act stub received, one list item per argument,
        and the workflow file the wrapper handed it.
    """
    done, argv, _shared, _created, workflow = run_act(
        DB_PATH, act_env, shared_cache, frontend
    )
    done.check_returncode()
    return argv, workflow


def act_argv(act_env: str, shared_cache: str = "") -> list[str]:
    """Return the argv act got, with the cache frontend present.

    Args:
        act_env: value of ``ACT_ENV``.
        shared_cache: value of ``INFINITO_CACHE_SHARED_HOST_PATH``.

    Returns:
        The arguments the act stub received, one list item per argument.
    """
    return act_run(act_env, shared_cache)[0]


def option(argv: list[str], flag: str) -> list[str]:
    return [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == flag]


def env_items(argv: list[str]) -> list[str]:
    """Collect the ``ACT_ENV`` values passed behind each ``--env`` flag.

    Args:
        argv: arguments the act stub received.

    Returns:
        Every ``--env`` value in order, without the wrapper's own
        ``INFINITO_VULNERABILITY_DB_HOST_PATH`` pin.
    """
    return [
        value for value in option(argv, "--env") if not value.startswith(f"{DB_ENV}=")
    ]


def container_options(argv: list[str]) -> str:
    """Return the value passed behind ``--container-options``.

    Args:
        argv: arguments the act stub received.

    Returns:
        The job container options act was handed.
    """
    return option(argv, "--container-options")[0]


class TestActSharedPipCache(unittest.TestCase):
    def test_the_job_containers_share_the_hosts_pip_cache(self) -> None:
        argv = act_argv("disable=css", shared_cache=SHARED_PATH)
        words = shlex.split(container_options(argv))
        bind = words.index(f"{SHARED_PATH}:{SHARED_PATH}")
        self.assertEqual(words[bind - 1], "-v")
        self.assertIn(f"PIP_CACHE_DIR={SHARED_PATH}/pip", env_items(argv))

    def test_a_path_with_a_space_stays_one_bind(self) -> None:
        spaced = "/srv/shared cache"
        words = shlex.split(container_options(act_argv("", shared_cache=spaced)))
        self.assertIn(f"{spaced}:{spaced}", words)

    def test_the_default_job_container_options_survive_the_mount(self) -> None:
        options = container_options(act_argv("", shared_cache=SHARED_PATH))
        self.assertTrue(options.startswith("--privileged --label infinito.worktree="))

    def test_a_checkout_without_the_shared_folder_mounts_nothing(self) -> None:
        argv = act_argv("disable=css")
        self.assertNotIn("-v", shlex.split(container_options(argv)))
        self.assertEqual(env_items(argv), ["disable=css"])

    def test_without_the_cache_frontend_nothing_is_mounted(self) -> None:
        argv, workflow = act_run("disable=css", SHARED_PATH, frontend=False)
        self.assertNotIn("-v", shlex.split(container_options(argv)))
        self.assertEqual(env_items(argv), ["disable=css"])
        self.assertIn("          cache: pip\n", workflow)

    def test_setup_python_stops_snapshotting_the_shared_folder(self) -> None:
        _argv, workflow = act_run("", SHARED_PATH)
        self.assertNotIn("cache: pip", workflow)
        self.assertIn('          cache: ""\n', workflow)
        self.assertIn("          cache: npm\n", workflow)
        self.assertIn("cache-dependency-path: pyproject.toml", workflow)

    def test_setup_python_keeps_its_cache_without_the_shared_folder(self) -> None:
        _argv, workflow = act_run("", "")
        self.assertEqual(workflow, WORKFLOW)


class TestVulnerabilityDatabaseBind(unittest.TestCase):
    def test_the_shared_databases_sit_at_the_host_path_in_the_job_container(
        self,
    ) -> None:
        done, argv, shared, _created, _workflow = run_act(DB_PATH)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"--volume {shared}:{shared}", container_options(argv))

    def test_the_job_steps_receive_the_host_path(self) -> None:
        _done, argv, shared, _created, _workflow = run_act(DB_PATH)
        self.assertIn(f"{DB_ENV}={shared}", option(argv, "--env"))

    def test_the_directory_exists_before_act_binds_it(self) -> None:
        _done, _argv, _shared, created, _workflow = run_act(DB_PATH)
        self.assertTrue(created)

    def test_the_job_container_keeps_the_host_daemon_socket(self) -> None:
        _done, argv, _shared, _created, _workflow = run_act(DB_PATH)
        self.assertNotIn("--container-daemon-socket", argv)

    def test_the_default_options_survive(self) -> None:
        _done, argv, _shared, _created, _workflow = run_act(DB_PATH)
        self.assertTrue(
            container_options(argv).startswith(
                "--privileged --label infinito.worktree=infinito-test "
            )
        )

    def test_an_unset_host_path_starts_no_act_run(self) -> None:
        done, argv, _shared, created, _workflow = run_act(None)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual((argv, created), ([], False))

    def test_the_shared_pip_cache_and_the_databases_share_one_option(self) -> None:
        argv = act_argv("", shared_cache=SHARED_PATH)
        words = shlex.split(container_options(argv))
        self.assertIn(f"{SHARED_PATH}:{SHARED_PATH}", words)
        self.assertEqual(len(option(argv, "--container-options")), 1)
        self.assertIn("--volume", words)


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


if __name__ == "__main__":
    unittest.main()
