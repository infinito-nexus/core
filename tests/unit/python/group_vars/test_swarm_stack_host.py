import unittest
from pathlib import Path

import jinja2

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

SWARM_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "18_swarm.yml"


def _render(expr, **variables):
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False),
        undefined=jinja2.StrictUndefined,
    )
    return env.from_string(expr).render(**variables).strip()


class TestSingleStackHost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        swarm_vars = load_yaml_any(str(SWARM_VARS))
        cls.expr = swarm_vars["IS_STACK_HOST"]
        cls.stack_host_expr = swarm_vars["STACK_HOST"]
        cls.compose_mode_expr = swarm_vars["IS_COMPOSE_MODE"]

    def stack_hosts(self, managers, nodes, mode="swarm"):
        groups = {"svc-swarm-manager": managers, "svc-swarm-node": nodes}
        hosts = []
        for host in nodes:
            stack_host = _render(
                self.stack_host_expr, inventory_hostname=host, groups=groups
            )
            compose_mode = _render(self.compose_mode_expr, DEPLOYMENT_MODE=mode)
            rendered = _render(
                self.expr,
                IS_COMPOSE_MODE=compose_mode == "True",
                inventory_hostname=host,
                STACK_HOST=stack_host,
            )
            if rendered == "True":
                hosts.append(host)
        return hosts

    def test_three_managers_yield_exactly_one_stack_host(self):
        managers = ["m1", "m2", "m3"]
        self.assertEqual(self.stack_hosts(managers, [*managers, "w1"]), ["m1"])

    def test_single_manager_is_stack_host(self):
        self.assertEqual(self.stack_hosts(["m1"], ["m1", "w1", "w2"]), ["m1"])

    def test_compose_mode_every_host_is_stack_host(self):
        self.assertEqual(self.stack_hosts([], ["h1"], mode="compose"), ["h1"])

    def test_stack_host_is_derived_from_stack_host_var(self):
        self.assertIn("STACK_HOST", self.expr)
        self.assertNotIn("svc-swarm-manager", self.expr)


class TestSwarmManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expr = load_yaml_any(str(SWARM_VARS))["IS_SWARM_MANAGER"]

    def managers(self, managers, nodes):
        groups = {"svc-swarm-manager": managers, "svc-swarm-node": nodes}
        return [
            host
            for host in nodes
            if _render(self.expr, inventory_hostname=host, groups=groups) == "True"
        ]

    def test_every_manager_is_flagged(self):
        managers = ["m1", "m2", "m3"]
        self.assertEqual(self.managers(managers, [*managers, "w1"]), managers)

    def test_no_manager_group_flags_nobody(self):
        self.assertEqual(self.managers([], ["h1"]), [])


if __name__ == "__main__":
    unittest.main()
