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
ACT_STUB = (
    "#!/usr/bin/env bash\n"
    'printf \'%s\\0\' "$@" >"${STUB_LOG}"\n'
    'while [ "$#" -gt 0 ]; do\n'
    '\tif [ "$1" = -W ]; then cp "$2" "${STUB_WORKFLOW}"; fi\n'
    "\tshift\n"
    "done\n"
)
DOCKER_STUB = (
    "#!/usr/bin/env bash\n"
    '[ -n "${STUB_FRONTEND}" ] && [ "$*" = "inspect infinito-package-cache-frontend" ]\n'
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


def act_run(
    act_env: str, shared_cache: str = "", frontend: bool = True
) -> tuple[list[str], str]:
    """Run the act wrapper against ``act`` and ``docker`` stubs.

    Args:
        act_env: value of ``ACT_ENV``.
        shared_cache: value of ``INFINITO_CACHE_SHARED_HOST_PATH``; empty
            stands for a checkout without the shared cache folder.
        frontend: whether the package-cache frontend container exists.

    Returns:
        The arguments the act stub received, one list item per argument,
        and the workflow file the wrapper handed it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in (("act", ACT_STUB), ("docker", DOCKER_STUB)):
            stub = Path(tmp) / name
            stub.write_text(body)
            stub.chmod(0o755)
        workflow = Path(tmp) / "call-test-deploy.yml"
        workflow.write_text(WORKFLOW)
        log = Path(tmp) / "act.argv"
        handed = Path(tmp) / "act.workflow"
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("BASH_ENV", SHARED, "ACT_CONTAINER_OPTIONS")
        }
        if shared_cache:
            env[SHARED] = shared_cache
        env.update(
            PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            STUB_WORKFLOW=str(handed),
            STUB_FRONTEND="1" if frontend else "",
            ACT_WORKFLOW=str(workflow),
            ACT_ENV=act_env,
            ACT_ACTION_CACHE_PATH=str(Path(tmp) / "actcache"),
            ACT_PLATFORM_IMAGE="catthehacker/ubuntu:act-latest",
            INFINITO_CONTAINER="infinito-test",
        )
        subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        argv = log.read_text().split("\0")[:-1]  # nocheck: cache-read  stub argv log
        return argv, handed.read_text()  # nocheck: cache-read  stub workflow copy


def act_argv(act_env: str, shared_cache: str = "") -> list[str]:
    """Return the argv act got, with the cache frontend present.

    Args:
        act_env: value of ``ACT_ENV``.
        shared_cache: value of ``INFINITO_CACHE_SHARED_HOST_PATH``.

    Returns:
        The arguments the act stub received, one list item per argument.
    """
    return act_run(act_env, shared_cache)[0]


def env_items(argv: list[str]) -> list[str]:
    """Collect the values passed behind each ``--env`` flag.

    Args:
        argv: arguments the act stub received.

    Returns:
        Every ``--env`` value in order.
    """
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == "--env"]


def container_options(argv: list[str]) -> str:
    """Return the value passed behind ``--container-options``.

    Args:
        argv: arguments the act stub received.

    Returns:
        The job container options act was handed.
    """
    return argv[argv.index("--container-options") + 1]


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
