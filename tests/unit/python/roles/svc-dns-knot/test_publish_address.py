from __future__ import annotations

import json
import re
import unittest
import unittest.mock as mock

import jinja2

from plugins.lookup.container_ports import LookupModule
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

APPLICATION_ID = "svc-dns-knot"
ROLE_DIR = PROJECT_ROOT / "roles" / APPLICATION_ID
COMPOSE = read_text(str(ROLE_DIR / ROLE_FILE_TEMPL_COMPOSE))
VARS = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_VARS_MAIN)))
SERVICES = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_META_SERVICES)))
ADDRESS = "203.0.113.10"
TOR_HOST = [APPLICATION_ID, "svc-net-tor"]
PLAIN_HOST = [APPLICATION_ID]
_TERM = re.compile(r"lookup\('container_ports',\s*(\{.*?\})\)", re.DOTALL)
_JINJA = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    autoescape=jinja2.select_autoescape(default_for_string=False),
)


def bound_addresses(template: str, group_names: list[str]) -> list[str | None]:
    """Args:
        template: the text of the knot ``compose.yml.j2``.
        group_names: the groups of the host the template renders for.

    Returns:
        The ``host_ip`` of every published DNS port, None where the port binds
        every address of the host.
    """
    bind_host = _JINJA.from_string(VARS["KNOT_BIND_HOST"]).render(
        networks={"internet": {"ip4": ADDRESS}}, group_names=group_names
    )
    (term,) = _TERM.findall(template)
    rendered = _JINJA.from_string("{{ " + term + " | tojson }}").render(
        KNOT_BIND_HOST=bind_host
    )
    lookup = LookupModule()
    lookup._loader = mock.MagicMock()
    applications = {APPLICATION_ID: {"services": SERVICES}}
    with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(
            run=lambda *_a, **_k: [applications]
        )
        block = lookup.run(
            [json.loads(rendered)], variables={"application_id": APPLICATION_ID}
        )[0]
    return [port.get("host_ip") for port in load_yaml_str(block)["ports"]]


class TestKnotPublishAddress(unittest.TestCase):
    def test_beside_tor_dns_binds_only_the_internet_address(self):
        self.assertEqual(bound_addresses(COMPOSE, TOR_HOST), [ADDRESS, ADDRESS])

    def test_without_tor_dns_binds_only_the_internet_address(self):
        self.assertEqual(bound_addresses(COMPOSE, PLAIN_HOST), [ADDRESS, ADDRESS])

    def test_negative_control_no_host_renders_the_wildcard_bind(self):
        for groups in (TOR_HOST, PLAIN_HOST):
            with self.subTest(groups=groups):
                self.assertNotEqual(bound_addresses(COMPOSE, groups), [None, None])

    def test_negative_control_a_term_without_the_ip_binds_every_address(self):
        planted = COMPOSE.replace(", 'ip': KNOT_BIND_HOST", "")
        self.assertNotEqual(planted, COMPOSE)
        self.assertEqual(bound_addresses(planted, TOR_HOST), [None, None])


if __name__ == "__main__":
    unittest.main()
