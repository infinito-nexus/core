import unittest

from jinja2 import Environment

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles" / "web-app-fider" / "tasks"
MODES = ("compose", "swarm")

_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


def _to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUTHY


def _guard_holds(task, context) -> bool:
    when = task.get("when", [])
    guards = when if isinstance(when, list) else [when]
    env = Environment(autoescape=True)
    env.filters["bool"] = _to_bool
    return all(bool(env.compile_expression(expr)(**context)) for expr in guards)


def _run_tasks(*, sso: bool, stack_host: bool, mode: str, tenants: int) -> list:
    context = {
        "FIDER_OIDC_ENABLED": sso,
        "FIDER_MCP_ENABLED": False,
        "IS_STACK_HOST": stack_host,
        "DEPLOYMENT_MODE": mode,
        "fider_tenant_count": {"rows": [[tenants]]},
    }
    executed: list = []
    for include in load_yaml_any(str(TASKS / "00_core.yml")):
        target = include.get("include_tasks")
        if not isinstance(target, str) or not (TASKS / target).is_file():
            continue
        if not _guard_holds(include, context):
            continue
        executed.extend(
            task
            for task in load_yaml_any(str(TASKS / target))
            if _guard_holds(task, context)
        )
    return executed


def _tenant_posts(tasks: list) -> list:
    return [
        task
        for task in tasks
        if str(task.get("uri_retry", {}).get("url", "")).endswith("/_api/tenants")
        or "POST /_api/tenants" in str(task.get("ansible.builtin.shell", ""))
    ]


def _configures_keycloak(tasks: list) -> bool:
    return any(
        str(task.get("database_query", {}).get("query_file", "")).endswith(
            "configure-oidc-provider.sql"
        )
        for task in tasks
    )


class TestTenantBootstrapGate(unittest.TestCase):
    def test_fresh_stack_host_posts_one_tenant_with_and_without_sso(self):
        for sso in (True, False):
            for mode in MODES:
                with self.subTest(sso=sso, mode=mode):
                    tasks = _run_tasks(sso=sso, stack_host=True, mode=mode, tenants=0)
                    self.assertEqual(len(_tenant_posts(tasks)), 1)

    def test_existing_tenant_is_not_posted_again(self):
        for sso in (True, False):
            for mode in MODES:
                with self.subTest(sso=sso, mode=mode):
                    tasks = _run_tasks(sso=sso, stack_host=True, mode=mode, tenants=1)
                    self.assertEqual(_tenant_posts(tasks), [])

    def test_keycloak_provider_is_configured_only_with_sso(self):
        for sso in (True, False):
            for mode in MODES:
                with self.subTest(sso=sso, mode=mode):
                    tasks = _run_tasks(sso=sso, stack_host=True, mode=mode, tenants=1)
                    self.assertEqual(_configures_keycloak(tasks), sso)

    def test_non_stack_host_runs_no_bootstrap(self):
        for sso in (True, False):
            for mode in MODES:
                with self.subTest(sso=sso, mode=mode):
                    tasks = _run_tasks(sso=sso, stack_host=False, mode=mode, tenants=0)
                    self.assertEqual(tasks, [])


if __name__ == "__main__":
    unittest.main()
