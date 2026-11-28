import unittest

from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from plugins.filter.resource_filter import resource_filter
from utils.cache.files import PROJECT_ROOT, read_text

TEMPLATES = PROJECT_ROOT / "roles" / "sys-svc-container" / "templates"
DEPLOY = "deploy.yml.j2"
APPLICATION_ID = "web-app-example"
LABEL = "ldap-socket"
CONSTRAINT = f"node.labels.{LABEL} == true"
NODE_LABEL_BLOCK = (
    "{% set _node_label = lookup('applications') | resource_filter(application_id, "
    "'node_label', service_name | default(''), '') %}\n"
    "{% if _node_label %}\n"
    "{% set _ = _constraints.append('node.labels.' ~ _node_label ~ ' == true') %}\n"
    "{% endif %}\n"
)
SERVICES = {
    "example": {"name": "example"},
    "cron": {"replicas": 1, "node_label": LABEL},
    "worker": {"node_label": ""},
    "manager_cron": {"placement": "manager", "node_label": LABEL},
}
BASE = {
    "RUNTIME": "local",
    "SANDBOX_NODE_LABEL": "kata-capable",
    "DOCKER_RESTART_POLICY": "unless-stopped",
    "RESOURCE_CPUS": "1",
    "RESOURCE_HOST_CPUS": "8",
    "RESOURCE_MEM_LIMIT": "1g",
    "RESOURCE_MEM_RESERVATION": "256m",
    "RESOURCE_PIDS_LIMIT": "512",
}


def render(service_name, compose_mode, overrides=None):
    """
    Args:
        service_name: the service of ``SERVICES`` whose deploy block is rendered.
        compose_mode: ``swarm`` or ``compose``.
        overrides: ``{template name: source}`` that replace the real templates.

    Returns:
        The rendered ``deploy:`` block.
    """
    env = Environment(
        loader=ChoiceLoader(
            [DictLoader(overrides or {}), FileSystemLoader(str(TEMPLATES))]
        ),
        trim_blocks=True,
        lstrip_blocks=False,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = boolean
    env.filters["resource_filter"] = resource_filter
    env.filters["swarm_restart_condition"] = lambda value: value
    applications = {APPLICATION_ID: {"services": SERVICES}}

    def _lookup(name, *args, **kwargs):
        if name == "applications":
            return applications
        if name == "compose_replicas":
            return "replicas: 1"
        if name == "roles_with_placement":
            return []
        if name == "config":
            return False
        raise AssertionError(f"unexpected lookup: {name}")

    env.globals["lookup"] = _lookup
    return env.get_template(DEPLOY).render(
        {
            **BASE,
            "compose_mode": compose_mode,
            "application_id": APPLICATION_ID,
            "service_name": service_name,
            "groups": {},
        }
    )


def constraints(rendered):
    lines = [line.strip() for line in rendered.splitlines()]
    return [line[2:] for line in lines if line.startswith("- node.")]


class TestNodeLabelPlacement(unittest.TestCase):
    def test_a_service_with_a_node_label_runs_only_on_the_labelled_nodes(self):
        self.assertEqual(constraints(render("cron", "swarm")), [CONSTRAINT])

    def test_an_empty_node_label_adds_no_constraint(self):
        self.assertEqual(constraints(render("worker", "swarm")), [])

    def test_a_sibling_without_a_node_label_stays_unconstrained(self):
        self.assertEqual(constraints(render("example", "swarm")), [])

    def test_the_node_label_composes_with_the_node_role(self):
        self.assertEqual(
            constraints(render("manager_cron", "swarm")),
            ["node.role == manager", CONSTRAINT],
        )

    def test_compose_mode_renders_no_constraint(self):
        self.assertEqual(render("cron", "compose").strip(), "")

    def test_negative_control_a_renderer_without_the_block_drops_the_label(self):
        source = read_text(str(TEMPLATES / DEPLOY))
        self.assertIn(NODE_LABEL_BLOCK, source)
        stripped = source.replace(NODE_LABEL_BLOCK, "")
        self.assertNotIn(
            CONSTRAINT,
            constraints(render("cron", "swarm", overrides={DEPLOY: stripped})),
        )


if __name__ == "__main__":
    unittest.main()
