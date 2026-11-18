from __future__ import annotations

import shlex
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT
from ._fake_bao import install, read_state, run

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
TASK_NAME = "Keep only the current version of every tenant secret"


def role_vars() -> dict[str, Any]:
    return load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))


def workspace_tasks() -> list[dict[str, Any]]:
    return load_yaml_any(str(ROLE_DIR / "tasks" / "07_workspaces.yml"))


def versions_task() -> dict[str, Any]:
    return next(task for task in workspace_tasks() if TASK_NAME in task["name"])


def command() -> list[str]:
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["quote"] = lambda value: shlex.quote(str(value))
    values = role_vars()
    rendered = environment.from_string(versions_task()["ansible.builtin.shell"]).render(
        OPENBAO_LOCAL_CID="openbao",
        OPENBAO_TENANT_MOUNT=values["OPENBAO_TENANT_MOUNT"],
        OPENBAO_TENANT_MAX_VERSIONS=values["OPENBAO_TENANT_MAX_VERSIONS"],
    )
    return ["sh", "-c", rendered]


class TestTenantVersions(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())
        self.env = install(self.scratch)

    def tearDown(self) -> None:
        shutil.rmtree(self.scratch, ignore_errors=True)

    def test_a_fresh_tenant_mount_keeps_one_version(self) -> None:
        result = run(command(), self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OPENBAO_CHANGED", result.stdout)
        state = read_state(self.scratch)
        self.assertEqual(state["config"]["tenant/config"]["max_versions"], "1")

    def test_a_converged_mount_is_not_written_again(self) -> None:
        run(command(), self.env)
        result = run(command(), self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("OPENBAO_CHANGED", result.stdout)
        self.assertEqual(read_state(self.scratch)["writes"], ["tenant/config"])

    def test_a_refused_write_fails_the_task(self) -> None:
        result = run(command(), {**self.env, "FAKE_BAO_WRITE_FAIL": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("OPENBAO_CHANGED", result.stdout)

    def test_only_the_tenant_mount_drops_old_versions(self) -> None:
        self.assertNotIn("loop", versions_task())
        self.assertIn("OPENBAO_TENANT_MOUNT", versions_task()["ansible.builtin.shell"])

    def test_the_setting_follows_the_mount_creation(self) -> None:
        names = [task["name"] for task in workspace_tasks()]
        mounts = next(
            i for i, name in enumerate(names) if "KV v2 workspace mounts" in name
        )
        self.assertEqual(names[mounts + 1], versions_task()["name"])


if __name__ == "__main__":
    unittest.main()
