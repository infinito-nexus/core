"""A service published in host mode for the node onion runs on the stack host.

Only the stack host publishes the hidden service, and a host-mode publish binds
only the node the task runs on, so a manager placement alone may put the
backend where the onion never dials it. Docker matches ``node.hostname``
against the full kernel nodename, which ``ansible_facts['nodename']`` carries and
``ansible_facts['hostname']`` cuts at the first dot.
"""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TEMPLATES = Path(PROJECT_ROOT) / "roles" / "sys-svc-container" / "templates"
SWARM = load_yaml_any(str(Path(PROJECT_ROOT) / "group_vars" / "all" / "18_swarm.yml"))
HOSTNAME = Path(PROJECT_ROOT) / "roles" / "sys-hostname" / "tasks" / "00_core.yml"
BACKENDS = [
    {"application": "svc-db-openldap", "service": "openldap", "port": 389},
    {"application": "svc-db-mariadb", "service": "mariadb", "port": 3306},
]
BASE = {
    "compose_mode": "swarm",
    "application_id": "svc-db-mariadb",
    "service_name": "mariadb",
    "RUNTIME": "local",
    "DOCKER_RESTART_POLICY": "unless-stopped",
    "RESOURCE_CPUS": "1",
    "RESOURCE_HOST_CPUS": "8",
    "RESOURCE_MEM_LIMIT": "1g",
    "RESOURCE_MEM_RESERVATION": "256m",
    "RESOURCE_PIDS_LIMIT": "512",
    "groups": {},
}


def _render(**overrides) -> str:
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        trim_blocks=True,
        lstrip_blocks=False,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    environment.filters["bool"] = bool
    environment.filters["resource_filter"] = lambda _apps, *_a, **_k: ""
    environment.filters["swarm_restart_condition"] = lambda value: value

    def _lookup(name, *args, **kwargs):
        if name == "applications":
            return {}
        if name == "compose_replicas":
            return "replicas: 1"
        if name == "roles_with_placement":
            return ["svc-db-mariadb", "svc-db-openldap"]
        raise AssertionError(f"unexpected lookup: {name}")

    environment.globals["lookup"] = _lookup
    return environment.get_template("deploy.yml.j2").render({**BASE, **overrides})


def _constraints(rendered: str) -> list[str]:
    lines = [line.strip() for line in rendered.splitlines()]
    return [line[2:] for line in lines if line.startswith("- node.")]


class TestOnionStackHostPin(unittest.TestCase):
    def test_an_onion_backend_is_pinned_to_the_stack_host(self) -> None:
        constraints = _constraints(
            _render(SWARM_ONION_HOST_BACKENDS=BACKENDS, STACK_HOST_NODE="mgr-01")
        )
        self.assertIn("node.hostname == mgr-01", constraints)
        self.assertIn("node.role == manager", constraints)

    def test_another_service_of_the_application_is_not_pinned(self) -> None:
        constraints = _constraints(
            _render(
                SWARM_ONION_HOST_BACKENDS=BACKENDS,
                STACK_HOST_NODE="mgr-01",
                service_name="exporter",
            )
        )
        self.assertNotIn("node.hostname == mgr-01", constraints)

    def test_another_application_is_not_pinned(self) -> None:
        constraints = _constraints(
            _render(
                SWARM_ONION_HOST_BACKENDS=BACKENDS,
                STACK_HOST_NODE="mgr-01",
                application_id="web-app-gitea",
                service_name="mariadb",
            )
        )
        self.assertNotIn("node.hostname == mgr-01", constraints)

    def test_without_onion_backends_nothing_is_pinned(self) -> None:
        constraints = _constraints(_render())
        self.assertFalse([c for c in constraints if c.startswith("node.hostname")])

    def test_the_stack_host_node_is_its_full_kernel_nodename(self) -> None:
        environment = Environment(autoescape=select_autoescape())
        expression = environment.from_string(SWARM["STACK_HOST_NODE"])
        facts = {"hostname": "mgr1", "nodename": "mgr1.example.org"}
        self.assertEqual(
            expression.render(
                STACK_HOST="mgr1.example.org",
                hostvars={"mgr1.example.org": {"ansible_facts": facts}},
            ),
            "mgr1.example.org",
        )
        self.assertIn(
            "node.hostname == mgr1.example.org",
            _constraints(
                _render(
                    SWARM_ONION_HOST_BACKENDS=BACKENDS,
                    STACK_HOST_NODE=expression.render(
                        STACK_HOST="mgr1.example.org",
                        hostvars={"mgr1.example.org": {"ansible_facts": facts}},
                    ),
                )
            ),
        )

    def test_without_facts_the_node_name_is_the_one_sys_hostname_sets(self) -> None:
        environment = Environment(autoescape=select_autoescape())
        self.assertEqual(
            environment.from_string(SWARM["STACK_HOST_NODE"]).render(
                STACK_HOST="mgr-01", hostvars={"mgr-01": {"ansible_facts": {}}}
            ),
            "mgr-01",
        )
        (task,) = [
            task
            for block in load_yaml_any(str(HOSTNAME))
            for task in block.get("block", [block])
            if "ansible.builtin.hostname" in task
        ]
        self.assertEqual(
            task["ansible.builtin.hostname"]["name"], "{{ inventory_hostname }}"
        )


if __name__ == "__main__":
    unittest.main()
