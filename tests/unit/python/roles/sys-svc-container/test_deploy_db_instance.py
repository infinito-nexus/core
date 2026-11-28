import unittest

import jinja2

from plugins.filter.swarm.placement import swarm_placement_constraints
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_str

TEMPLATE = "roles/sys-svc-container/templates/deploy.yml.j2"
SEEDED_KEY = "services.postgres.ha.seeded_after_converge"
CONFIG: dict[str, object] = {}


def _lookup(name, *args, **_kwargs):
    if name == "roles_with_placement":
        return ["svc-db-postgres"]
    if name == "compose_replicas":
        return f"replicas: {args[0]}" if args else "replicas: 3"
    if name == "applications":
        return {}
    if name == "config":
        return CONFIG.get(args[1], args[-1])
    raise AssertionError(f"unexpected lookup {name}")


def _render(**variables):
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False),
        loader=jinja2.FileSystemLoader(str(PROJECT_ROOT)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["resource_filter"] = lambda _apps, _app, _key, _svc, default, **_kw: (
        default
    )
    env.filters["swarm_restart_condition"] = lambda value: "any"
    env.filters["swarm_placement_constraints"] = swarm_placement_constraints
    env.globals["lookup"] = _lookup
    base = {
        "compose_mode": "swarm",
        "application_id": "svc-db-postgres",
        "service_name": "postgres",
        "db_instance": None,
        "groups": {},
        "hostvars": {},
        "DOCKER_RESTART_POLICY": "always",
        "RESOURCE_CPUS": "1",
        "RESOURCE_HOST_CPUS": 4,
        "RESOURCE_MEM_LIMIT": "1g",
        "RESOURCE_PIDS_LIMIT": 512,
        "RESOURCE_MEM_RESERVATION": "512m",
        "RUNTIME": "dev",
        "SWARM_NODE_LABEL_STACK_HOST": "infinito.stack_host",
        "SWARM_NODE_LABEL_HOST_ID": "infinito.host_id",
        "SWARM_SERVICE_LABEL_SEED_WAIT": "infinito.seed_wait",
    }
    base.update(variables)
    rendered = env.get_template(TEMPLATE).render(**base)
    return load_yaml_str("svc:\n" + rendered)["svc"]["deploy"]


class TestDeployDbInstance(unittest.TestCase):
    def tearDown(self):
        CONFIG.clear()

    def test_seeded_instance_carries_the_seed_wait_label(self):
        CONFIG[SEEDED_KEY] = True
        deploy = _render(db_instance={"host": "mgr-02", "host_id": "mgr-02"})
        self.assertEqual(deploy["labels"], {"infinito.seed_wait": "true"})

    def test_instance_without_the_flag_has_no_label(self):
        deploy = _render(db_instance={"host": "mgr-02", "host_id": "mgr-02"})
        self.assertNotIn("labels", deploy)

    def test_standalone_form_never_carries_the_label(self):
        CONFIG[SEEDED_KEY] = True
        self.assertNotIn("labels", _render())

    def test_standalone_keeps_manager_pin(self):
        deploy = _render()
        self.assertEqual(deploy["placement"]["constraints"], ["node.role == manager"])

    def test_manager_role_pins_to_stack_host_with_several_managers(self):
        deploy = _render(
            STACK_HOST="mgr-01",
            groups={"svc-swarm-manager": ["mgr-01", "mgr-02", "mgr-03"]},
            hostvars={"mgr-01": {"ansible_facts": {"hostname": "node-one"}}},
        )
        self.assertEqual(
            deploy["placement"]["constraints"],
            ["node.role == manager", "node.labels.infinito.stack_host == true"],
        )

    def test_single_manager_has_no_stack_host_pin(self):
        deploy = _render(
            STACK_HOST="mgr-01",
            groups={"svc-swarm-manager": ["mgr-01"]},
        )
        self.assertEqual(deploy["placement"]["constraints"], ["node.role == manager"])

    def test_ha_instance_pins_to_its_host_label_not_the_manager_role(self):
        deploy = _render(
            db_instance={"host": "mgr-02", "host_id": "mgr-02"},
            hostvars={"mgr-02": {"ansible_facts": {"hostname": "node-two"}}},
        )
        self.assertEqual(deploy["replicas"], 1)
        self.assertEqual(
            deploy["placement"]["constraints"],
            ["node.labels.infinito.host_id == mgr-02"],
        )


if __name__ == "__main__":
    unittest.main()
