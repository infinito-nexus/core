import unittest

import jinja2

from utils import PROJECT_ROOT
from utils.cache.applications import get_application_defaults
from utils.cache.yaml import load_yaml_str
from utils.roles.applications.config import get

TEMPLATE = "roles/sys-svc-compose/templates/db_endpoint.yml.j2"


SYSCTLS = {}
LOOKUP_CALLS = []


def _lookup(name, *args, **kwargs):
    LOOKUP_CALLS.append((name, args, kwargs))
    if name == "db_endpoint":
        return SYSCTLS.get(args[0], {})
    if name == "db_instances":
        return "svc-dcs-etcd"
    if name == "roles_with_placement":
        return ["svc-db-postgres"]
    if name == "compose_replicas":
        return f"replicas: {args[0]}" if args else "replicas: 3"
    if name == "applications":
        return {}
    if name == "config":
        if args[0] == "sys-svc-compose":
            return get(get_application_defaults(), args[0], args[1])
        return args[-1]
    if name == "container_image":
        return f'image: "{args[1]}:pinned"'
    if name == "compose_restart":
        return "restart: always"
    if name == "container_volumes":
        return f"secrets:\n  - source: {args[0]}_cfg"
    if name == "container_networks":
        return "networks:\n  default:"
    raise AssertionError(f"unexpected lookup {name}")


def _render(**variables):
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False),
        loader=jinja2.FileSystemLoader(str(PROJECT_ROOT)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["resource_filter"] = lambda _apps, _app, key, svc, default: (
        default if key == "platform_arch" else f"{svc}-{key}"
    )
    env.filters["swarm_restart_condition"] = lambda value: "any"
    env.globals["lookup"] = _lookup
    base = {
        "compose_mode": "swarm",
        "application_id": "svc-db-postgres",
        "service_name": "postgres",
        "STACK_HOST": "mgr-01",
        "groups": {"svc-swarm-manager": ["mgr-01", "mgr-02", "mgr-03"]},
        "hostvars": {},
        "DOCKER_RESTART_POLICY": "always",
        "RESOURCE_CPUS": "1",
        "RESOURCE_MEM_LIMIT": "1g",
        "RESOURCE_PIDS_LIMIT": 512,
        "RESOURCE_MEM_RESERVATION": "512m",
        "RUNTIME": "dev",
        "SWARM_SERVICE_LABEL_DB_ENDPOINT": "infinito.db_endpoint",
    }
    base.update(variables)
    rendered = env.get_template(TEMPLATE).render(**base)
    return load_yaml_str("services:\n" + rendered)["services"]


class TestDbEndpointService(unittest.TestCase):
    def setUp(self):
        self.services = _render()

    def test_takes_over_the_engine_service_name(self):
        self.assertEqual(list(self.services), ["postgres"])
        self.assertEqual(self.services["postgres"]["image"], "haproxy:pinned")

    def test_carries_the_write_endpoint_label(self):
        self.assertEqual(
            self.services["postgres"]["deploy"]["labels"],
            {"infinito.db_endpoint": "true"},
        )

    def test_two_unpinned_replicas_one_per_node(self):
        deploy = self.services["postgres"]["deploy"]
        self.assertEqual(deploy["replicas"], 2)
        self.assertEqual(deploy["placement"], {"max_replicas_per_node": 1})

    def test_sized_from_the_haproxy_entry(self):
        limits = self.services["postgres"]["deploy"]["resources"]["limits"]
        self.assertEqual(limits["memory"], "haproxy-mem_limit")

    def test_image_pinned_once_in_sys_svc_compose(self):
        calls = [c for c in LOOKUP_CALLS if c[0] == "container_image"]
        self.assertEqual(calls[-1][1], ("sys-svc-compose", "haproxy"))

    def test_no_sysctls_on_an_unprivileged_port(self):
        self.assertNotIn("sysctls", self.services["postgres"])

    def test_privileged_port_gets_its_sysctl(self):
        SYSCTLS["svc-db-openldap"] = {"net.ipv4.ip_unprivileged_port_start": 389}
        self.addCleanup(SYSCTLS.clear)
        services = _render(application_id="svc-db-openldap", service_name="openldap")
        self.assertEqual(
            services["openldap"]["sysctls"],
            {"net.ipv4.ip_unprivileged_port_start": 389},
        )

    def test_hardened(self):
        service = self.services["postgres"]
        self.assertTrue(service["read_only"])
        self.assertNotIn("ports", service)
        self.assertEqual(service["secrets"], [{"source": "haproxy_cfg"}])


if __name__ == "__main__":
    unittest.main()
