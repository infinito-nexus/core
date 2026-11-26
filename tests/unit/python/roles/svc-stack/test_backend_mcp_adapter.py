from __future__ import annotations

import unittest

from ansible.plugins.filter.core import FilterModule as CoreFilters
from jinja2 import Environment, StrictUndefined, select_autoescape

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
CONSUMER = "web-app-consumer"
INSTANCE_ROOT = "/srv/instances/web-app-consumer"
ADAPTER = {
    "mcp": {
        "implementation": "adapter",
        "endpoint": {"service_key": "api"},
        "adapter": {"upstream_credential": True},
    },
    "services": {"api": {"enabled": True}},
}


def _include(task: dict) -> str:
    return str(task.get("ansible.builtin.include_tasks"))


def _staging() -> dict:
    return next(
        task for task in load_yaml_any(str(BACKEND)) if INSTANCE in _include(task)
    )


def _evaluate(expression: str, config: dict):
    """
    Args:
        expression: a ``when`` clause or a templated task var of the staging.
        config: the consumer's configuration the ``config`` lookup reads.

    Returns:
        The native value the expression yields.
    """

    def lookup(name, *terms):
        if name == "container":
            return INSTANCE_ROOT
        if name != "config" or terms[0] != CONSUMER:
            raise AssertionError(f"unexpected lookup {name!r} {terms!r}")
        _, path, *default = terms
        node = config
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                if default:
                    return default[0]
                raise KeyError(path)
            node = node[part]
        return node

    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(CoreFilters().filters())
    inner = expression.strip().removeprefix("{{").removesuffix("}}")
    return env.compile_expression(inner)(
        lookup=lookup, stack_consumer_id=CONSUMER, application_id=CONSUMER
    )


def _staged(config: dict) -> bool:
    """
    Args:
        config: the consumer's configuration the ``config`` lookup reads.

    Returns:
        Whether every ``when`` clause of the staging task holds.
    """
    return all(bool(_evaluate(clause, config)) for clause in _staging()["when"])


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

    def test_the_staging_runs_for_an_enabled_adapter_consumer(self) -> None:
        self.assertTrue(_staged(ADAPTER))

    def test_the_staging_skips_a_native_or_disabled_consumer(self) -> None:
        native = {**ADAPTER, "mcp": {**ADAPTER["mcp"], "implementation": "native"}}
        disabled = {**ADAPTER, "services": {"api": {"enabled": False}}}
        for name, config in (("native", native), ("disabled", disabled)):
            with self.subTest(consumer=name):
                self.assertFalse(_staged(config))

    def test_an_adapter_without_an_endpoint_service_fails_loudly(self) -> None:
        unnamed = {**ADAPTER, "mcp": {"implementation": "adapter"}}
        with self.assertRaises(KeyError):
            _staged(unnamed)

    def test_the_staging_builds_in_the_consumer_instance_dir(self) -> None:
        self.assertEqual(
            _evaluate(_staging()["vars"]["mcp_adapter_instance_dir"], ADAPTER),
            f"{INSTANCE_ROOT}/mcp",
        )

    def test_the_upstream_key_follows_the_adapter_meta(self) -> None:
        upstream_key = _staging()["vars"]["mcp_adapter_upstream_key"]
        self.assertIs(_evaluate(upstream_key, ADAPTER), True)
        keyless = {**ADAPTER, "mcp": {**ADAPTER["mcp"], "adapter": {}}}
        self.assertIs(_evaluate(upstream_key, keyless), False)

    def test_every_adapter_role_builds_from_the_staged_dir(self) -> None:  # nocheck: test.text-presence -- policy lint over every role whose meta/mcp.yml declares an adapter  # fmt: skip
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
