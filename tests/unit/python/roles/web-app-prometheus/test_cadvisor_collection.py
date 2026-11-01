from __future__ import annotations

import json
import re
import unittest
from collections import defaultdict
from types import SimpleNamespace

from ansible.plugins.filter.core import to_bool
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

ROLE = PROJECT_ROOT / "roles/web-app-prometheus"
COMPOSE = ROLE / ROLE_FILE_TEMPL_COMPOSE
PROMETHEUS_CONFIG = ROLE / "templates/configuration/prometheus.yml.j2"
CADVISOR_DEFAULT_HOUSEKEEPING_SECONDS = 1
IDENTITY_LABELS = {
    "com.docker.compose.project",
    "com.docker.compose.service",
    "com.docker.swarm.service.name",
    "com.docker.stack.namespace",
}

INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
    "roles/sys-svc-container/templates/base.yml.j2": "",
}

STUBBED = {
    "application_id": "web-app-prometheus",
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


def _lookup(name, *_terms, **_kwargs):
    if name == "volume":
        return SimpleNamespace(target="/stub", targets=defaultdict(lambda: "/stub"))
    if name == "native_metrics_apps":
        return []
    return ""


def cadvisor_command(*, compose: bool) -> list[str]:
    """Render ``compose.yml.j2`` and return the cadvisor service's command.

    Args:
        compose: ``IS_COMPOSE_MODE``.

    Returns:
        The arguments compose appends to the image entrypoint.
    """
    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        loader=DictLoader(INCLUDES),
    )
    env.filters["bool"] = to_bool
    env.filters["to_json"] = json.dumps
    env.filters["entity_name"] = str
    env.globals["lookup"] = _lookup
    rendered = env.from_string(read_text(str(COMPOSE))).render(
        **STUBBED, IS_COMPOSE_MODE=compose
    )
    service = load_yaml_str(rendered)["services"]["cadvisor"]
    if "command" not in service:
        raise AssertionError(
            "cadvisor runs with its defaults again: 1s housekeeping and every "
            "container label stamped on every series"
        )
    return service["command"]


def flags(command: list[str]) -> dict[str, str]:
    """Split ``--name=value`` arguments.

    Args:
        command: the rendered cadvisor command.

    Returns:
        Each flag name mapped to its value.
    """
    return dict(argument.split("=", 1) for argument in command)


def seconds(duration: str) -> int:
    """Convert a Go duration written in whole seconds or minutes.

    Args:
        duration: e.g. ``10s`` or ``1m``.

    Returns:
        The duration in seconds.
    """
    match = re.fullmatch(r"(\d+)([sm])", duration)
    if match is None:
        raise AssertionError(f"unexpected duration {duration!r}")
    return int(match.group(1)) * {"s": 1, "m": 60}[match.group(2)]


def scrape_interval_seconds() -> int:
    match = re.search(
        r"^\s*scrape_interval:\s*(\S+)\s*$",
        read_text(str(PROMETHEUS_CONFIG)),
        re.MULTILINE,
    )
    if match is None:
        raise AssertionError(
            "prometheus.yml.j2 no longer sets a global scrape_interval"
        )
    return seconds(match.group(1))


class TestCadvisorCollection(unittest.TestCase):
    def test_every_argument_is_a_single_name_value_token(self) -> None:
        for compose in (True, False):
            with self.subTest(compose=compose):
                for argument in cadvisor_command(compose=compose):
                    self.assertRegex(
                        argument,
                        r"^--[a-z_]+=\S+$",
                        "Go's flag package stops parsing at the first bare "
                        "value, so '--store_container_labels false' would "
                        "silently drop every flag after it",
                    )

    def test_container_labels_are_not_stamped_on_every_series(self) -> None:
        for compose in (True, False):
            with self.subTest(compose=compose):
                self.assertEqual(
                    flags(cadvisor_command(compose=compose)).get(
                        "--store_container_labels"
                    ),
                    "false",
                    "cadvisor stamps every series of every cgroup with the union "
                    "of all containers' label keys, image labels included, so "
                    "each scrape grows with containers times distinct images "
                    "and OOM-kills cadvisor on a host with 100+ containers",
                )

    def test_only_the_docker_identity_labels_are_kept(self) -> None:
        command = flags(cadvisor_command(compose=True))
        self.assertIn("--whitelisted_container_labels", command)
        self.assertEqual(
            set(command["--whitelisted_container_labels"].split(",")),
            IDENTITY_LABELS,
            "the compose and swarm identity labels keep series groupable per "
            "app and per swarm service while the label union stays fixed",
        )

    def test_housekeeping_refreshes_each_sample_before_the_next_scrape(self) -> None:
        command = flags(cadvisor_command(compose=True))
        self.assertIn("--housekeeping_interval", command)
        housekeeping = seconds(command["--housekeeping_interval"])
        self.assertGreater(
            housekeeping,
            CADVISOR_DEFAULT_HOUSEKEEPING_SECONDS,
            "the 1s default re-reads every cgroup each second and keeps about "
            "120 samples per cgroup in the 2-minute in-memory cache",
        )
        self.assertLess(
            2 * housekeeping,
            scrape_interval_seconds(),
            "cadvisor jitters the housekeeping interval up to twice its value "
            "and serves timestamped samples, so a longer interval makes "
            "consecutive scrapes return the same sample",
        )


if __name__ == "__main__":
    unittest.main()
