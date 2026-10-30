from __future__ import annotations

import importlib.util
import unittest
from unittest import mock

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from plugins.filter.cookie_scope import domain_strings
from plugins.filter.network_of import in_network
from plugins.lookup.tls import LookupModule as TlsLookup
from utils.cache.files import read_text
from utils.networks.instances import labelled, network_instances
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

filter_loader.add_directory(str(PROJECT_ROOT / "plugins" / "filter"))

APP = "web-svc-logout"
ROLE = PROJECT_ROOT / "roles" / APP
TEMPLATE = ROLE / ROLE_FILE_TEMPL_COMPOSE
VARS = ROLE / ROLE_FILE_VARS_MAIN

_spec = importlib.util.spec_from_file_location(
    "logout_domain_filters", ROLE / "filter_plugins" / "domain_filters.py"
)
_domain_filters = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_domain_filters)
logout_domains = _domain_filters.FilterModule().filters()["logout_domains"]

NODE = "a" * 56 + ".onion"
CLEAR = "logout.example.test"
ONION = f"logout.{NODE}"
SHOP = "shop.example.test"
SHOP_ONION = f"shop.{NODE}"

TLS_VARIABLES = {"TLS_ENABLED": True, "TLS_MODE": "letsencrypt"}
INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n\n",
    "roles/sys-svc-container/templates/base.yml.j2": "",
}


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer]


def render(conductor: list[str], shop: list[str]) -> dict:
    """Render the logout compose file for one node.

    Args:
        conductor: the domains the node serves web-svc-logout on.
        shop: the domains of one logout-enabled application.

    Returns:
        The ``services`` mapping of the rendered compose file.
    """
    domains = {APP: conductor, "web-app-shop": shop}
    applications = {app: {"services": {"logout": {"enabled": True}}} for app in domains}
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "domains":
            return _Stub(domains)
        if name == "applications":
            return _Stub(applications)
        return real_get(name, *args, **kwargs)

    def lookup(name, *terms, **_kwargs):
        if name == "domains":
            return domains
        if name == "applications":
            return applications
        if name == "tls":
            tls = TlsLookup()
            tls._loader = None
            tls._templar = None
            return tls.run(list(terms), variables=TLS_VARIABLES)[0]
        return ""

    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    templar = Templar(
        loader=DataLoader(), variables={**declared, "application_id": APP}
    )
    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        loader=DictLoader(INCLUDES),
    )
    env.filters.update(
        labelled=labelled,
        network_instances=network_instances,
        domain_strings=domain_strings,
        in_network=in_network,
        logout_domains=logout_domains,
    )
    env.globals["lookup"] = lookup
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        instances = templar.template(declared["LOGOUT_INSTANCES"])
        rendered = env.from_string(read_text(str(TEMPLATE))).render(
            application_id=APP,
            group_names=sorted(domains),
            LOGOUT_INSTANCES=instances,
            LOGOUT_CONTAINER="logout",
            DOCKER_BIND_HOST="127.0.0.1",
        )
    return yaml.safe_load(rendered)["services"]


def siblings(services: dict) -> dict[str, str]:
    return {
        name: service["environment"]["LOGOUT_SIBLINGS"]
        for name, service in services.items()
    }


class TestSingleNetwork(unittest.TestCase):
    def test_a_clearnet_conductor_hands_off_nowhere(self) -> None:
        self.assertEqual(siblings(render([CLEAR], [SHOP])), {"logout": ""})

    def test_a_tor_only_conductor_hands_off_nowhere(self) -> None:
        self.assertEqual(siblings(render([ONION], [SHOP_ONION])), {"logout": ""})


class TestClearnetAndTor(unittest.TestCase):
    def setUp(self) -> None:
        self.services = render([CLEAR, ONION], [SHOP, SHOP_ONION])

    def test_each_conductor_lists_exactly_the_other(self) -> None:
        self.assertEqual(
            siblings(self.services),
            {"logout": f"http://{ONION}", "logout-onion": f"https://{CLEAR}"},
        )

    def test_each_conductor_still_sweeps_only_its_own_network(self) -> None:
        self.assertEqual(
            {
                name: service["environment"]["LOGOUT_DOMAINS"]
                for name, service in self.services.items()
            },
            {
                "logout": f"https://{CLEAR},https://{SHOP}",
                "logout-onion": f"http://{ONION},http://{SHOP_ONION}",
            },
        )


if __name__ == "__main__":
    unittest.main()
