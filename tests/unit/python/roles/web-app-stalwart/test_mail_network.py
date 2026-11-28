from __future__ import annotations

import re
import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError
from jinja2 import Environment, select_autoescape

from plugins.lookup.container_ports import LookupModule as ContainerPortsLookup
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.networks.render import (
    compute_external_network_roles,
    render_compose_networks,
    render_container_networks,
)
from utils.roles.applications.services.registry import discover_role_services
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
)
from utils.tls.common import get_path

ROLES = PROJECT_ROOT / "roles"
PROVIDER = "web-app-stalwart"
WRAPPER = "web-app-email"
NETWORK = entity_name(PROVIDER)
MODES = ("compose", "swarm")
COMPOSE_TEMPLATE = ROLES / PROVIDER / ROLE_FILE_TEMPL_COMPOSE
NETWORK_TASKS = ROLES / "sys-svc-compose" / "tasks" / "utils" / "network"
NETWORK_CREATE = NETWORK_TASKS / "create.yml"
OVERLAY_CREATE = NETWORK_TASKS / "create" / "overlay.yml"
SWARM_VARS = PROJECT_ROOT / "group_vars" / "all" / "18_swarm.yml"
SUBMISSION_PORT = 587
PORT_TERM = re.compile(r"\['stalwart', '(\w+)', \w+\]")
TOPIC_FILES = {"services": ROLE_FILE_META_SERVICES, "networks": ROLE_FILE_META_NETWORKS}


def _meta(role: str, file: str) -> dict:
    return load_yaml_any(str(ROLES / role / file), default_if_missing={}) or {}


def _rendered(value, role: str):
    if isinstance(value, str) and "{{" in value:
        env = Environment(autoescape=select_autoescape(default_for_string=False))
        return env.from_string(value).render(group_names=[WRAPPER, PROVIDER, role])
    return value


def _lookup_config(role: str, path: str, default):
    topic, _, rest = path.partition(".")
    if topic not in TOPIC_FILES:
        return default
    return _rendered(get_path(_meta(role, TOPIC_FILES[topic]), rest, default), role)


def _lookup_database(_role: str, _key: str):
    return None


def _registry() -> dict:
    return discover_role_services(
        PROVIDER,
        {
            "services": _meta(PROVIDER, ROLE_FILE_META_SERVICES),
            "networks": _meta(PROVIDER, ROLE_FILE_META_NETWORKS),
        },
    )


def _consumers() -> list[str]:
    roles = []
    for path in sorted(ROLES.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        role = path.relative_to(ROLES).parts[0]
        email = _meta(role, ROLE_FILE_META_SERVICES).get("email")
        if role == PROVIDER or not isinstance(email, dict):
            continue
        if all(
            str(_rendered(email.get(flag), role)).lower() == "true"
            for flag in ("enabled", "shared")
        ):
            roles.append(role)
    return roles


def _kwargs(application_id: str, mode: str) -> dict:
    return {
        "application_id": application_id,
        "deployment_mode": mode,
        "registry": _registry(),
        "lookup_config": _lookup_config,
        "lookup_database": _lookup_database,
    }


class TestMailNetworkTopology(unittest.TestCase):
    def test_stalwart_answers_to_its_service_name_on_the_mail_network(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                block = render_container_networks(
                    entity_name=entity_name, **_kwargs(PROVIDER, mode)
                )
                self.assertIn(f"  {NETWORK}:\n    aliases:\n      - {NETWORK}", block)
                self.assertIn("  default:", block)

    def test_the_sidecars_never_answer_to_the_service_name(self):
        template = read_text(COMPOSE_TEMPLATE)
        self.assertEqual(
            template.count("lookup('container_networks', provider_self_alias=False)"),
            2,
        )
        for mode in MODES:
            with self.subTest(mode=mode):
                block = render_container_networks(
                    entity_name=entity_name,
                    provider_self_alias=False,
                    **_kwargs(PROVIDER, mode),
                )
                self.assertIn(f"  {NETWORK}:\n    {{}}", block)

    def test_every_mail_consumer_joins_the_mail_network(self):
        consumers = _consumers()
        self.assertIn("web-app-gitea", consumers)
        self.assertIn("web-app-nextcloud", consumers)
        for mode in MODES:
            for consumer in consumers:
                with self.subTest(mode=mode, consumer=consumer):
                    attachment = render_container_networks(
                        entity_name=entity_name, **_kwargs(consumer, mode)
                    )
                    definition = render_compose_networks(
                        entity_name=entity_name, **_kwargs(consumer, mode)
                    )
                    self.assertIn(f"  {NETWORK}:\n    {{}}", attachment)
                    self.assertIn(f"  {NETWORK}:\n    external: true", definition)
                    external = compute_external_network_roles(**_kwargs(consumer, mode))
                    self.assertIn(PROVIDER, external)

    def test_a_role_without_mail_stays_off_the_mail_network(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                self.assertNotIn(
                    f"  {NETWORK}:",
                    render_container_networks(
                        entity_name=entity_name, **_kwargs("web-app-fediwall", mode)
                    ),
                )

    def test_the_mail_network_is_a_bridge_in_compose(self):
        tasks = load_yaml_any(str(NETWORK_CREATE))
        bridge = next(task for task in tasks if "bridge" in task["name"])
        self.assertIn("create/bridge.yml", str(bridge["ansible.builtin.include_tasks"]))
        self.assertIn("not (IS_SWARM_MODE | bool)", bridge["when"])
        self.assertIsNone(_lookup_config(PROVIDER, "networks.local.force_bridge", None))
        block = render_compose_networks(
            entity_name=entity_name, **_kwargs(PROVIDER, "compose")
        )
        self.assertIn(f"  {NETWORK}:\n    external: true", block)
        self.assertIn("    driver: bridge", block)

    def test_the_mail_network_is_an_encrypted_overlay_in_swarm(self):
        tasks = load_yaml_any(str(NETWORK_CREATE))
        overlay = next(task for task in tasks if "overlay" in task["name"])
        self.assertIn("(IS_SWARM_MODE | bool)", overlay["when"])
        create = next(
            task
            for task in load_yaml_any(str(OVERLAY_CREATE))
            if "Ensure" in task["name"]
        )
        argv = create["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[argv.index("--driver") + 1], "overlay")
        self.assertIn(
            "encrypted={{ 'true' if swarm.network.encryption else 'false' }}", argv
        )
        swarm = load_yaml_any(str(SWARM_VARS))["swarm"]
        self.assertIs(swarm["network"]["encryption"], True)
        block = render_compose_networks(
            entity_name=entity_name,
            swarm_encrypted=True,
            **_kwargs(PROVIDER, "swarm"),
        )
        self.assertIn(f"  {NETWORK}:\n    external: true", block)
        self.assertIn('      encrypted: "true"', block)


class TestSubmissionNeverPublished(unittest.TestCase):
    def setUp(self):
        self.services = _meta(PROVIDER, ROLE_FILE_META_SERVICES)
        self.ports = self.services["stalwart"]["ports"]

    def test_587_is_an_internal_port_only(self):
        self.assertEqual(self.ports["internal"]["submission"], SUBMISSION_PORT)
        for group in ("public", "onion", "local"):
            with self.subTest(group=group):
                declared = self.ports.get(group) or {}
                self.assertNotIn("submission", declared)
                self.assertNotIn(SUBMISSION_PORT, declared.values())

    def _render_ports(self, mode: str, terms: list[list[str]]) -> str:
        lookup = ContainerPortsLookup()
        plugin = MagicMock()
        plugin.run.return_value = [{PROVIDER: {"services": self.services}}]
        with patch(
            "plugins.lookup.container_ports.lookup_loader.get", return_value=plugin
        ):
            return lookup.run(
                terms,
                variables={"application_id": PROVIDER, "DEPLOYMENT_MODE": mode},
            )[0]

    def test_the_rendered_stack_publishes_no_587_in_either_mode(self):
        protocols = PORT_TERM.findall(read_text(COMPOSE_TEMPLATE))
        self.assertIn("smtp", protocols)
        self.assertNotIn("submission", protocols)
        terms = [["stalwart", protocol, "127.0.0.1"] for protocol in protocols]
        for mode in MODES:
            with self.subTest(mode=mode):
                block = self._render_ports(mode, terms)
                self.assertIn(":25:25", block)
                self.assertNotIn(f":{SUBMISSION_PORT}", block)

    def test_no_host_port_exists_to_publish_587_on(self):
        for mode in MODES:
            with self.subTest(mode=mode), self.assertRaises(AnsibleError):
                self._render_ports(mode, [["stalwart", "submission", "127.0.0.1"]])


if __name__ == "__main__":
    unittest.main()
