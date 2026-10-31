from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "act" / "workflow.sh"
ACT_STUB = '#!/usr/bin/env bash\nprintf \'%s\\0\' "$@" >"${STUB_LOG}"\n'
EXTRA_VARS = json.dumps(
    {
        "applications": {
            "web-app-erpnext": {"services": {"erpnext": {"server_scripts": True}}},
            "web-app-cst-demo": {"billing": {"bank": "Verify Bank, IBAN DE00 0000"}},
        }
    }
)


def act_argv(act_env: str) -> list[str]:
    """Run the act wrapper against an ``act`` stub and return the argv it got.

    Args:
        act_env: value of ``ACT_ENV``.

    Returns:
        The arguments the stub received, one list item per argument.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "act"
        stub.write_text(ACT_STUB)
        stub.chmod(0o755)
        workflow = Path(tmp) / "call-test-deploy.yml"
        workflow.write_text("on: workflow_dispatch\n")
        log = Path(tmp) / "act.argv"
        env = {k: v for k, v in os.environ.items() if k != "BASH_ENV"}
        env.update(
            PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
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
        return log.read_text().split("\0")[:-1]  # nocheck: cache-read  stub argv log


def env_items(argv: list[str]) -> list[str]:
    """Collect the values passed behind each ``--env`` flag.

    Args:
        argv: arguments the act stub received.

    Returns:
        Every ``--env`` value in order.
    """
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == "--env"]


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
