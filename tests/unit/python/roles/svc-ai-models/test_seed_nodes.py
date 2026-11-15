from __future__ import annotations

import unittest

from jinja2.nativetypes import NativeEnvironment

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-ai-models"
GROUPS = {
    "svc-swarm-manager": ["manager"],
    "svc-swarm-node": ["manager", "worker-1", "worker-2"],
}


def _seed_nodes(**context: object) -> list[str]:
    variables = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
    template = NativeEnvironment().from_string(variables["MODELS_SEED_NODES"])
    return template.render(**context)


class TestSeedNodes(unittest.TestCase):
    def test_a_swarm_seeds_every_manager_and_node_once(self) -> None:
        nodes = _seed_nodes(
            groups=GROUPS, IS_SWARM_MODE=True, inventory_hostname="manager"
        )
        self.assertEqual(nodes, ["manager", "worker-1", "worker-2"])

    def test_compose_seeds_only_the_deploy_host(self) -> None:
        nodes = _seed_nodes(
            groups=GROUPS, IS_SWARM_MODE=False, inventory_hostname="host"
        )
        self.assertEqual(nodes, ["host"])

    def test_the_seed_and_the_refusal_run_on_every_seed_node(self) -> None:
        for name in ("seed.yml", "require.yml"):
            with self.subTest(file=name):
                [task] = load_yaml_any(str(ROLE / "tasks" / "utils" / name))
                self.assertEqual(
                    (task["loop"], task["delegate_to"]),
                    ("{{ MODELS_SEED_NODES }}", "{{ models_node }}"),
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
