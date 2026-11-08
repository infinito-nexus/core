from __future__ import annotations

import unittest
from unittest import mock

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from plugins.lookup.compose_only import LookupModule as ComposeOnlyLookup
from plugins.lookup.container_image import LookupModule as ContainerImageLookup
from plugins.lookup.image import LookupModule as ImageLookup
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.networks.instances import labelled, network_instances
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

APP = "web-app-dashboard"
ROLE = PROJECT_ROOT / "roles" / APP
TEMPLATE = ROLE / ROLE_FILE_TEMPL_COMPOSE
DASHBOARD = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))["dashboard"]

NODE = "a" * 56 + ".onion"
CLEAR = "dashboard.example.test"
ONION = f"dashboard.{NODE}"
REGISTRY = {"host": "registry.example", "port": "5000"}
PREFIX = {"compose": "", "swarm": "registry.example:5000/"}

INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n\n",
    "roles/sys-svc-container/templates/deploy.yml.j2": "",
}


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer]


def render(domains: list[str], mode: str) -> dict:
    """Render the dashboard compose file for one node.

    Args:
        domains: the domains the node serves the dashboard on.
        mode: the deployment mode, ``compose`` or ``swarm``.

    Returns:
        The ``services`` mapping of the rendered compose file.
    """
    variables = {"DEPLOYMENT_MODE": mode, "swarm": {"registry": REGISTRY}}
    applications = {APP: {"services": {"dashboard": DASHBOARD}}}
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "applications":
            return _Stub(applications)
        if name == "image":
            return ImageLookup()
        return real_get(name, *args, **kwargs)

    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        loader=DictLoader(INCLUDES),
    )
    env.filters["labelled"] = labelled

    def lookup(name, *terms, **_kwargs):
        if name == "template":
            return env.from_string(read_text(str(PROJECT_ROOT / terms[0]))).render()
        if name == "compose_only":
            return ComposeOnlyLookup().run(list(terms), variables=variables)[0]
        if name == "container_image":
            return ContainerImageLookup().run(list(terms), variables=variables)[0]
        return ""

    env.globals["lookup"] = lookup
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        rendered = env.from_string(read_text(str(TEMPLATE))).render(
            application_id=APP,
            DASHBOARD_INSTANCES=network_instances(domains),
            DASHBOARD_IMAGE=DASHBOARD["image"],
            DASHBOARD_VERSION=DASHBOARD["version"],
            DASHBOARD_CONTAINER=DASHBOARD["name"],
            DOCKER_BIND_HOST="127.0.0.1",
        )
    return load_yaml_str(rendered)["services"]


def builders(services: dict) -> list[str]:
    return sorted(name for name, service in services.items() if "build" in service)


class TestSingleNetwork(unittest.TestCase):
    def test_the_only_dashboard_builds_its_image(self) -> None:
        for mode in PREFIX:
            with self.subTest(mode=mode):
                services = render([CLEAR], mode)
                self.assertEqual(sorted(services), ["dashboard"])
                self.assertEqual(builders(services), ["dashboard"])


class TestClearnetAndTor(unittest.TestCase):
    def setUp(self) -> None:
        self.services = {mode: render([CLEAR, ONION], mode) for mode in PREFIX}

    def test_both_networks_keep_their_dashboard(self) -> None:
        for mode, services in self.services.items():
            with self.subTest(mode=mode):
                self.assertEqual(sorted(services), ["dashboard", "dashboard-onion"])

    def test_the_image_is_built_once_per_deploy(self) -> None:
        for mode, services in self.services.items():
            with self.subTest(mode=mode):
                self.assertEqual(
                    builders(services),
                    ["dashboard"],
                    "two services building one Dockerfile under one tag make "
                    "`compose build` run two BuildKit builds of the same image "
                    "in parallel",
                )

    def test_the_onion_twin_runs_the_image_the_clearnet_dashboard_builds(
        self,
    ) -> None:
        for mode, services in self.services.items():
            with self.subTest(mode=mode):
                expected = f"{PREFIX[mode]}dashboard_custom:{DASHBOARD['version']}"
                self.assertEqual(services["dashboard"]["image"], expected)
                self.assertEqual(services["dashboard-onion"]["image"], expected)

    def test_the_build_bases_on_the_configured_upstream_image(self) -> None:
        for mode, services in self.services.items():
            with self.subTest(mode=mode):
                self.assertEqual(
                    services["dashboard"]["build"],
                    {
                        "context": ".",
                        "dockerfile": "Dockerfile",
                        "args": {
                            "DASHBOARD_IMAGE": DASHBOARD["image"],
                            "DASHBOARD_VERSION": DASHBOARD["version"],
                        },
                    },
                )

    def test_compose_never_pulls_the_locally_built_tag(self) -> None:
        compose = self.services["compose"]
        self.assertEqual(compose["dashboard"]["pull_policy"], "never")
        self.assertEqual(compose["dashboard-onion"]["pull_policy"], "never")

    def test_swarm_carries_no_pull_policy(self) -> None:
        for name, service in self.services["swarm"].items():
            with self.subTest(service=name):
                self.assertNotIn("pull_policy", service)


if __name__ == "__main__":
    unittest.main()
