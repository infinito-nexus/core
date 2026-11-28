import importlib.util
import unittest

from jinja2 import StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    load_applications_from_roles_dir,
    ordered_primary_service_entries,
)
from utils.roles.entity.name import entity_name

from . import PROJECT_ROOT

STACK = PROJECT_ROOT / "roles" / "svc-stack"
CONSUMER = "web-app-gitea"
CANONICAL_DOMAIN = "git.infinito.test"
CANONICAL_PORT = 8031
DECLARED_PORT = 9000


def _include(tasks_file: str) -> dict:
    """
    Args:
        tasks_file: a task file of svc-stack, relative to its tasks directory.

    Returns:
        The file's include_tasks task.
    """
    return next(
        task
        for task in load_yaml_any(str(STACK / "tasks" / tasks_file))
        if "ansible.builtin.include_tasks" in task
    )


def _stack_vhosts():
    spec = importlib.util.spec_from_file_location(
        "stack_vhosts", STACK / "filter_plugins" / "stack_vhosts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.stack_vhosts


def _lookup(name, *args):
    if name == "config":
        canonical = {
            f"services.{entity_name(CONSUMER)}.ports.local.http": CANONICAL_PORT
        }
        return canonical.get(args[1], args[2])
    if name == "domain":
        return CANONICAL_DOMAIN
    if name == "domains":
        return []
    raise AssertionError(f"unexpected lookup({name!r}, ...)")


def _render(expression: str, **variables):
    """
    Args:
        expression: one Jinja expression of a svc-stack task.
        variables: the variables the task sees.

    Returns:
        The native value the expression renders to.
    """
    env = NativeEnvironment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(entity_name=entity_name, stack_vhosts=_stack_vhosts())
    return env.from_string(expression).render(lookup=_lookup, **variables)


class TestFrontendServiceSpot(unittest.TestCase):
    def setUp(self):
        self.repo_root = PROJECT_ROOT
        self.roles_dir = self.repo_root / "roles"
        self.applications = load_applications_from_roles_dir(self.roles_dir)
        self.service_registry = build_service_registry_from_roles_dir(self.roles_dir)
        self.ordered = ordered_primary_service_entries(
            self.service_registry,
            self.roles_dir,
        )

    def _index(self, role_name: str) -> int:
        for index, entry in enumerate(self.ordered):
            if entry["role"] == role_name:
                return index
        self.fail(f"Role {role_name} not found in ordered service registry")
        return -1

    def test_bucket_order_is_monotonic(self):
        bucket_order = {
            "universal": 0,
            "workstation": 1,
            "server": 2,
            "web-svc": 3,
            "web-app": 4,
        }
        actual = [bucket_order[entry["bucket"]] for entry in self.ordered]
        self.assertEqual(actual, sorted(actual))

    def test_dashboard_is_loaded_after_matomo(self):
        self.assertLess(self._index("web-app-matomo"), self._index("web-app-dashboard"))

    def test_discourse_is_loaded_after_matomo(self):
        self.assertLess(self._index("web-app-matomo"), self._index("web-app-discourse"))

    def test_keycloak_respects_run_after_dependencies(self):
        self.assertLess(self._index("web-app-matomo"), self._index("web-app-keycloak"))
        self.assertLess(
            self._index("web-app-stalwart"), self._index("web-app-keycloak")
        )
        self.assertLess(self._index("web-app-email"), self._index("web-app-keycloak"))


class TestFrontProxyFallback(unittest.TestCase):
    def test_front_proxy_falls_back_to_canonical_port_and_domain(self):
        vhosts = _render(_include("proxy.yml")["loop"], application_id=CONSUMER)
        self.assertEqual(vhosts, [{"key": "default", "domain": CANONICAL_DOMAIN}])
        self.assertEqual(
            _render(
                _include("proxy/domain.yml")["vars"]["front_proxy_http_port"],
                front_proxy_vhost=vhosts[0],
                front_proxy_application_id=CONSUMER,
            ),
            CANONICAL_PORT,
        )

    def test_a_declared_vhost_port_wins_over_the_canonical_port(self):
        self.assertEqual(
            _render(
                _include("proxy/domain.yml")["vars"]["front_proxy_http_port"],
                front_proxy_vhost={"http_port": DECLARED_PORT},
                front_proxy_application_id=CONSUMER,
            ),
            DECLARED_PORT,
        )


if __name__ == "__main__":
    unittest.main()
