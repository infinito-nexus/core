import unittest
from pathlib import Path

from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.resource_filter import resource_filter
from plugins.lookup.compose_replicas import LookupModule as ComposeReplicas
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import iter_roles_with_placement

TEMPLATES = Path(PROJECT_ROOT) / "roles" / "sys-svc-container" / "templates"
ROLES = Path(PROJECT_ROOT) / "roles"

BASE = {
    "compose_mode": "swarm",
    "RUNTIME": "local",
    "SANDBOX_NODE_LABEL": "kata-capable",
    "DOCKER_RESTART_POLICY": "unless-stopped",
    "RESOURCE_CPUS": "1",
    "RESOURCE_HOST_CPUS": "8",
    "RESOURCE_MEM_LIMIT": "1g",
    "RESOURCE_MEM_RESERVATION": "256m",
    "RESOURCE_PIDS_LIMIT": "512",
}


def render(application_id, service_name, services, groups=None, templates=TEMPLATES):
    """
    Args:
        application_id: the role whose service is rendered.
        service_name: the compose service, a key of ``services``.
        services: the role's ``meta/services.yml`` content.
        groups: the inventory groups, none by default.
        templates: the directory holding ``deploy.yml.j2``.

    Returns:
        The rendered ``deploy:`` block.
    """
    env = Environment(
        loader=FileSystemLoader(str(templates)),
        trim_blocks=True,
        lstrip_blocks=False,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = boolean
    env.filters["resource_filter"] = resource_filter
    env.filters["swarm_restart_condition"] = lambda value: value
    applications = {application_id: {"services": services}}
    replicas = ComposeReplicas()
    swarm = {"DEPLOYMENT_MODE": "swarm", "application_id": application_id}

    def _lookup(name, *args, **kwargs):
        if name == "applications":
            return applications
        if name == "compose_replicas":
            return replicas.run(list(args), variables=swarm)[0]
        if name == "roles_with_placement":
            return iter_roles_with_placement(args[0])
        if name == "config":
            return False
        raise AssertionError(f"unexpected lookup: {name}")

    env.globals["lookup"] = _lookup
    return env.get_template("deploy.yml.j2").render(
        {
            **BASE,
            "application_id": application_id,
            "service_name": service_name,
            "groups": groups or {},
        }
    )


def constraints(rendered):
    lines = [line.strip() for line in rendered.splitlines()]
    return [line[2:] for line in lines if line.startswith("- node.")]


def placed_services():
    for meta in sorted(ROLES.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        services = load_yaml_any(str(meta)) or {}
        for name, entry in services.items():
            if isinstance(entry, dict) and entry.get("placement"):
                yield meta.parent.parent.name, name, services


class TestGlobalDeployMode(unittest.TestCase):
    def test_a_global_service_runs_one_task_per_node_without_a_role_constraint(self):
        services = {"tor": {"placement": "manager", "replicas": "global"}}
        rendered = render("svc-net-tor", "tor", services)
        self.assertIn("mode: global", rendered)
        self.assertNotIn("replicas:", rendered)
        self.assertEqual(constraints(rendered), [])

    def test_a_global_service_keeps_every_constraint_but_the_node_role(self):
        services = {
            "tor": {
                "placement": "manager",
                "replicas": "global",
                "platform_arch": "amd64",
            }
        }
        rendered = render(
            "svc-net-tor", "tor", services, groups={"svc-virt-kata": ["wrk-02"]}
        )
        self.assertEqual(
            constraints(rendered),
            ["node.platform.arch == amd64", "node.labels.kata-capable != true"],
        )

    def test_a_replicated_service_keeps_its_placement(self):
        for replicas in (1, 3, ""):
            with self.subTest(replicas=replicas):
                services = {"tor": {"placement": "manager", "replicas": replicas}}
                rendered = render("svc-net-tor", "tor", services)
                self.assertNotIn("mode: global", rendered)
                self.assertIn("node.role == manager", constraints(rendered))

    def test_every_other_placed_service_keeps_its_node_role_constraint(self):
        checked = 0
        for role, service, services in placed_services():
            replicas = resource_filter(
                {role: {"services": services}}, role, "replicas", service, ""
            )
            if str(replicas).strip() == "global":
                continue
            with self.subTest(role=role, service=service):
                rendered = render(role, service, services)
                self.assertIn(
                    f"node.role == {services[service]['placement']}",
                    constraints(rendered),
                )
                checked += 1
        self.assertGreater(checked, 20)


if __name__ == "__main__":
    unittest.main()
