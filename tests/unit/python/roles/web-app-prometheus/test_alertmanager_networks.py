"""Grafana and the Loki ruler reach the Alertmanager on the Prometheus network."""

from __future__ import annotations

import json
import unittest
from collections import defaultdict
from types import SimpleNamespace

from ansible.plugins.filter.core import to_bool
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml, load_yaml_str
from utils.networks.render import render_container_networks
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_NETWORKS, ROLE_FILE_TEMPL_COMPOSE

APPLICATION_ID = "web-app-prometheus"
ROLE = PROJECT_ROOT / "roles" / APPLICATION_ID
CONSUMERS = ("web-app-grafana", "web-svc-loki")

INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
    "roles/sys-svc-container/templates/base.yml.j2": "",
}

STUBBED = {
    "application_id": APPLICATION_ID,
    "PROMETHEUS_CONTAINER": "prometheus",
    "BLACKBOX_CONTAINER": "prometheus-blackbox",
    "ALERTMANAGER_CONTAINER": "prometheus-alertmanager",
    "CADVISOR_CONTAINER": "prometheus-cadvisor",
    "NODE_EXPORTER_CONTAINER": "prometheus-node-exporter",
    "DOCKER_BIND_HOST": "127.0.0.1",
    "PROMETHEUS_CONFIG_DOCKER": "/etc/prometheus/prometheus.yml",
    "BLACKBOX_CONFIG_DOCKER": "/etc/blackbox/blackbox.yml",
    "ALERTMANAGER_CONFIG_DOCKER": "/etc/alertmanager/alertmanager.yml",
    "PROMETHEUS_QUERY_TIMEOUT": "120s",
    "PROMETHEUS_PAGE_TITLE": "",
    "PROMETHEUS_MCP_ENABLED": False,
}


def _registry() -> dict[str, dict]:
    """
    Returns:
        A service registry holding the role's own network overlay.
    """
    overlay = load_yaml(str(ROLE / ROLE_FILE_META_NETWORKS))["overlay"]
    return {
        entity_name(APPLICATION_ID): {
            "role": APPLICATION_ID,
            "entity_name": entity_name(APPLICATION_ID),
            "overlay": overlay,
        }
    }


def render_services(deployment_mode: str) -> dict[str, dict]:
    """Render ``compose.yml.j2`` with the real per-service network attachment.

    Args:
        deployment_mode: ``compose`` or ``swarm``.

    Returns:
        The rendered ``services`` mapping.
    """

    def _lookup(name, *_terms, **kwargs):
        if name == "container_networks":
            return render_container_networks(
                application_id=APPLICATION_ID,
                deployment_mode=deployment_mode,
                registry=_registry(),
                entity_name=entity_name,
                lookup_config=lambda _app, _path, default: default,
                lookup_database=lambda _app, _key: "",
                **kwargs,
            )
        if name == "volume":
            return SimpleNamespace(target="/stub", targets=defaultdict(lambda: "/stub"))
        if name == "native_metrics_apps":
            return []
        return ""

    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        loader=DictLoader(INCLUDES),
    )
    env.filters["bool"] = to_bool
    env.filters["to_json"] = json.dumps
    env.filters["entity_name"] = entity_name
    env.globals["lookup"] = _lookup
    rendered = env.from_string(read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE))).render(
        **STUBBED, IS_COMPOSE_MODE=deployment_mode == "compose"
    )
    return load_yaml_str(rendered)["services"]


def network_aliases(service: dict, network: str) -> list[str] | None:
    """Aliases a service carries on ``network``, or None when it does not join it.

    Args:
        service: one rendered compose service.
        network: the network key.
    """
    networks = service.get("networks") or {}
    if network not in networks:
        return None
    return list((networks[network] or {}).get("aliases") or [])


class TestAlertmanagerNetworks(unittest.TestCase):
    def test_the_alertmanager_joins_the_network_its_consumers_join(self):
        shared = entity_name(APPLICATION_ID)
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                aliases = network_aliases(render_services(mode)["alertmanager"], shared)
                self.assertIsNotNone(
                    aliases,
                    f"{', '.join(CONSUMERS)} join only the {shared!r} network, so "
                    "the Alertmanager name falls through to the host resolver "
                    "and every notification is refused",
                )

    def test_the_alertmanager_does_not_answer_for_prometheus(self):
        shared = entity_name(APPLICATION_ID)
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                services = render_services(mode)
                self.assertIn(shared, network_aliases(services["prometheus"], shared))
                self.assertNotIn(
                    shared,
                    network_aliases(services["alertmanager"], shared) or [],
                    "the provider alias on the Alertmanager makes the Prometheus "
                    "datasource round-robin onto port 9090 of the Alertmanager",
                )

    def test_the_alertmanager_keeps_the_default_network(self):
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                self.assertIsNotNone(
                    network_aliases(render_services(mode)["alertmanager"], "default")
                )


if __name__ == "__main__":
    unittest.main()
