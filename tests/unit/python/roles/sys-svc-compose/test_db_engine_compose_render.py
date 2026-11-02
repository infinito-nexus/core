"""Render the four HA-capable engine compose templates through stubbed lookups.

Ansible lookups need a full inventory and play context, so every lookup is a
stub that echoes its own arguments; the test pins what the templates do with
the instance model, not what the lookups return.
"""

import json
import re
import unittest

import jinja2

from plugins.filter.swarm.instance_service import swarm_instance_service
from plugins.filter.swarm.placement import swarm_placement_constraints
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

ENGINES = {
    "svc-db-postgres": "postgres",
    "svc-db-mariadb": "mariadb",
    "svc-db-openldap": "openldap",
    "svc-db-redis": "redis",
}
SNAPSHOT = (
    PROJECT_ROOT / "tests/unit/python/roles/sys-svc-compose/db_engine_standalone.json"
)
HA_HOSTS = ["mgr-01", "mgr-02", "mgr-03"]
MEMORY_MB = 820


def _lookup_factory(application_id, model):
    def lookup(name, *args, **kwargs):
        if name == "db_instances":
            return "svc-dcs-etcd" if kwargs.get("coordination_store") else model
        if name == "db_endpoint":
            return {}
        if name in ("database", "objstore", "engine", "sso"):
            return False
        if name == "roles_with_placement":
            return [application_id]
        if name == "applications":
            return {}
        if name == "config":
            return args[-1]
        if name == "compose_replicas":
            return f"replicas: {args[0]}" if args else "replicas: 1"
        if name == "service_memory_mb":
            return MEMORY_MB
        if name == "volume":
            return {"target": f"/run/{args[-1]}"}
        if name == "template":
            return 'build:\n  context: "."\n  dockerfile: Dockerfile'
        instance = kwargs.pop("instance", None)
        if instance is not None:
            kwargs["instance"] = instance["service"]
        payload = json.dumps([name, list(args), kwargs], sort_keys=True, default=str)
        return f"x-{name}: {json.dumps(payload)}"

    return lookup


def render(application_id, model, loader=None, **variables):
    """Render one engine compose template.

    Args:
        application_id: engine role whose ``templates/compose.yml.j2`` renders.
        model: what ``lookup('db_instances')`` returns.
        loader: Jinja loader; defaults to the working tree.
        variables: extra template variables.

    Returns:
        The parsed compose document.
    """
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False),
        loader=loader or jinja2.FileSystemLoader(str(PROJECT_ROOT)),
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.ChainableUndefined,
    )
    env.filters["resource_filter"] = lambda _a, _b, _c, _d, default: default
    env.filters["swarm_restart_condition"] = lambda _value: "any"
    env.filters["has_env"] = lambda _app: False
    env.filters["bool"] = lambda value: str(value).lower() in ("1", "true", "yes", "on")
    env.filters["quote"] = lambda value: f"'{value}'"
    env.filters["swarm_instance_service"] = swarm_instance_service
    env.filters["swarm_placement_constraints"] = swarm_placement_constraints
    env.filters["regex_replace"] = lambda value, pattern, repl: re.sub(
        pattern, repl, value
    )
    env.globals["lookup"] = _lookup_factory(application_id, model)
    hosts = sorted({i["host"] for i in model["instances"] if i.get("host")})
    base = {
        "application_id": application_id,
        "entity_name": ENGINES[application_id],
        "compose_mode": "swarm",
        "DEPLOYMENT_MODE": "swarm",
        "DOCKER_RESTART_POLICY": "always",
        "RESOURCE_CPUS": "1",
        "RESOURCE_MEM_LIMIT": "1g",
        "RESOURCE_PIDS_LIMIT": 512,
        "RESOURCE_MEM_RESERVATION": "512m",
        "RUNTIME": "dev",
        "STACK_HOST": hosts[0] if hosts else "mgr-01",
        "SWARM_NODE_LABEL_STACK_HOST": "infinito.stack_host",
        "SWARM_NODE_LABEL_HOST_ID": "infinito.host_id",
        "SWARM_SERVICE_LABEL_SEED_WAIT": "infinito.seed_wait",
        "SWARM_SERVICE_LABEL_DB_ENDPOINT": "infinito.db_endpoint",
        "OPENLDAP_SERVICE": "openldap",
        "REDIS_MAXMEMORY_MB": MEMORY_MB,
        "groups": {"svc-swarm-manager": hosts or ["mgr-01"]},
        "hostvars": {h: {"ansible_facts": {"hostname": f"node-{h}"}} for h in hosts},
    }
    base.update(variables)
    template = f"roles/{application_id}/{ROLE_FILE_TEMPL_COMPOSE}"
    return load_yaml_str(env.get_template(template).render(**base))


def standalone_model(engine):
    return {
        "form": "standalone",
        "instances": [
            {"host": "mgr-01", "host_id": None, "service": engine, "legacy": True}
        ],
        "warnings": [],
    }


def ha_model(engine):
    return {
        "form": "ha",
        "instances": [
            {
                "host": host,
                "host_id": host,
                "service": f"{engine}-{host}",
                "legacy": host == "mgr-01",
            }
            for host in HA_HOSTS
        ],
        "warnings": [],
    }


class TestStandaloneUnchanged(unittest.TestCase):
    def test_one_host_renders_what_the_pre_ha_template_rendered(self):
        snapshot = json.loads(read_text(str(SNAPSHOT)))
        for application_id, engine in ENGINES.items():
            with self.subTest(application_id):
                self.assertEqual(
                    json.loads(
                        json.dumps(render(application_id, standalone_model(engine)))
                    ),
                    snapshot[application_id],
                )


class TestThreeHostHa(unittest.TestCase):
    def test_every_instance_is_pinned_to_its_host(self):
        for application_id, engine in ENGINES.items():
            with self.subTest(application_id):
                services = render(application_id, ha_model(engine))["services"]
                for host in HA_HOSTS:
                    deploy = services[f"{engine}-{host}"]["deploy"]
                    self.assertEqual(deploy["replicas"], 1)
                    self.assertEqual(
                        deploy["placement"]["constraints"],
                        [f"node.labels.infinito.host_id == {host}"],
                    )

    def test_no_instance_keeps_the_manager_pin(self):
        for application_id, engine in ENGINES.items():
            with self.subTest(application_id):
                services = render(application_id, ha_model(engine))["services"]
                for key, service in services.items():
                    constraints = (
                        service.get("deploy", {}).get("placement") or {}
                    ).get("constraints", [])
                    self.assertNotIn("node.role == manager", constraints, key)

    def test_the_write_endpoint_carries_the_engine_name(self):
        for application_id, engine in ENGINES.items():
            with self.subTest(application_id):
                services = render(application_id, ha_model(engine))["services"]
                endpoint = services[engine]
                self.assertIn("haproxy", json.dumps(endpoint["x-container_image"]))
                self.assertEqual(endpoint["deploy"]["replicas"], 2)
                self.assertEqual(
                    endpoint["deploy"]["placement"]["max_replicas_per_node"], 1
                )
                self.assertEqual(
                    endpoint["deploy"]["labels"], {"infinito.db_endpoint": "true"}
                )

    def test_only_the_write_endpoint_carries_the_endpoint_label(self):
        for application_id, engine in ENGINES.items():
            with self.subTest(application_id):
                services = render(application_id, ha_model(engine))["services"]
                labelled = sorted(
                    name
                    for name, service in services.items()
                    if "infinito.db_endpoint"
                    in ((service.get("deploy") or {}).get("labels") or {})
                )
                self.assertEqual(labelled, [engine])

    def test_instances_mount_their_own_volume(self):
        for application_id, engine in ENGINES.items():
            with self.subTest(application_id):
                services = render(application_id, ha_model(engine))["services"]
                for host in HA_HOSTS:
                    key = f"{engine}-{host}"
                    self.assertIn(
                        f'\\"instance\\": \\"{key}\\"', json.dumps(services[key])
                    )

    def test_redis_runs_one_sentinel_per_instance_host(self):
        services = render("svc-db-redis", ha_model("redis"))["services"]
        for host in HA_HOSTS:
            deploy = services[f"redis-sentinel-{host}"]["deploy"]
            self.assertEqual(
                deploy["placement"]["constraints"],
                [f"node.labels.infinito.host_id == {host}"],
            )


if __name__ == "__main__":
    unittest.main()
