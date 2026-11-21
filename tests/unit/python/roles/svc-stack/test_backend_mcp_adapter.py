from __future__ import annotations

import unittest

from tests.lint.ansible.services.test_litellm_consumer_contract import (
    _reaches_the_back_unit,
)
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_MCP,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

BACKEND = PROJECT_ROOT / "roles/svc-stack/tasks/backend.yml"
INSTANCE = "roles/svc-ai-mcp-adapter/tasks/instance.yml"
COMPOSE = "Load sys-svc-compose"
INSTANCE_DIR = (
    "[lookup('container', application_id, 'directories.instance'), 'mcp'] | path_join"
)
CREDENTIAL_FILE = "upstream.env"


def _include(task: dict) -> str:
    return str(task.get("ansible.builtin.include_tasks"))


def _staging() -> dict:
    return next(
        task for task in load_yaml_any(str(BACKEND)) if INSTANCE in _include(task)
    )


def _adapter_roles() -> dict[str, dict]:
    found = {}
    for path in sorted(PROJECT_ROOT.glob(f"roles/*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(path))
        if mcp.get("implementation") == "adapter":
            found[path.relative_to(PROJECT_ROOT / "roles").parts[0]] = mcp
    return found


class TestBackendMcpAdapter(unittest.TestCase):
    def test_the_backend_stages_the_adapter_before_compose(self) -> None:
        tasks = load_yaml_any(str(BACKEND))
        staging = next(i for i, task in enumerate(tasks) if INSTANCE in _include(task))
        compose = next(
            i for i, task in enumerate(tasks) if COMPOSE in str(task.get("name"))
        )
        self.assertLess(staging, compose)

    def test_the_staging_is_keyed_by_the_mcp_meta(self) -> None:
        task = _staging()
        when = " ".join(task["when"])
        self.assertIn("'mcp.implementation'", when)
        self.assertIn("'adapter'", when)
        self.assertIn("'mcp.endpoint.service_key'", when)
        self.assertNotIn("default(", when)
        self.assertIn(INSTANCE_DIR, task["vars"]["mcp_adapter_instance_dir"])
        self.assertIn(
            "'mcp.adapter.upstream_credential'",
            task["vars"]["mcp_adapter_upstream_key"],
        )

    def test_every_adapter_role_builds_from_the_staged_dir(self) -> None:
        for role in _adapter_roles():
            with self.subTest(role=role):
                vars_main = read_text(
                    str(PROJECT_ROOT / "roles" / role / ROLE_FILE_VARS_MAIN)
                )
                self.assertIn(INSTANCE_DIR, vars_main)

    def test_no_role_on_the_backend_stages_its_own_adapter(self) -> None:
        for role in _adapter_roles():
            role_dir = PROJECT_ROOT / "roles" / role
            if not _reaches_the_back_unit(role_dir):
                continue
            for path in sorted((role_dir / "tasks").glob("**/*.yml")):
                with self.subTest(role=role, path=path.name):
                    self.assertNotIn(INSTANCE, read_text(str(path)))

    def test_the_upstream_credential_follows_the_compose_file(self) -> None:
        for role, mcp in _adapter_roles().items():
            compose = PROJECT_ROOT / "roles" / role / ROLE_FILE_TEMPL_COMPOSE
            reads = compose.is_file() and CREDENTIAL_FILE in read_text(str(compose))
            with self.subTest(role=role):
                self.assertEqual(
                    mcp["adapter"].get("upstream_credential") is True, reads
                )


if __name__ == "__main__":
    unittest.main()
