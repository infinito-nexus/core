"""The openresty stream server that relays public LDAPS to slapd.

Compose reaches the loopback port OpenLDAP publishes; swarm has no such port,
so the relay names the openldap alias on the relay network and lets the
stream resolver look it up per connection.
"""

from __future__ import annotations

import re
import unittest
import unittest.mock as mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.lookup.proxy_pass import LookupModule as ProxyPassLookup
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

TEMPLATE = "roles/svc-db-openldap/templates/nginx.stream.conf.j2"
APPLICATION_ID = "svc-db-openldap"
SERVICES = load_yaml(
    str(PROJECT_ROOT / "roles" / APPLICATION_ID / ROLE_FILE_META_SERVICES)
)
APPLICATIONS = {APPLICATION_ID: {"services": SERVICES}}
CERT = {
    "files.cert": "/certs/fullchain.pem",
    "files.key": "/certs/privkey.pem",
    "files.ca": "",
}

COMPOSE_RENDER = (
    "server {\n"
    "    listen 636 ssl;\n"
    "    proxy_pass 127.0.0.1:389;\n"
    "    \n"
    "    ssl_certificate     /certs/fullchain.pem;\n"
    "ssl_certificate_key /certs/privkey.pem;\n"
    "}\n"
)


def _config(application_id: str, path: str) -> object:
    node: object = APPLICATIONS[application_id]
    for part in path.split("."):
        node = node[part]
    return node


def _proxy_pass(mode: str, terms: tuple, kwargs: dict) -> str:
    lookup = ProxyPassLookup()
    lookup._loader = mock.MagicMock()
    lookup._templar = None
    with mock.patch("plugins.lookup.proxy_pass.lookup_loader") as loader:
        loader.get.return_value = mock.MagicMock(
            run=lambda *_args, **_kwargs: [APPLICATIONS]
        )
        return lookup.run(list(terms), variables={"DEPLOYMENT_MODE": mode}, **kwargs)[0]


def render(mode: str) -> str:
    """Render the stream server the way Ansible's template module does.

    Args:
        mode: the DEPLOYMENT_MODE the proxy_pass lookup sees.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        trim_blocks=True,
        keep_trailing_newline=True,
    )

    def lookup(kind: str, *terms: str, **kwargs: object) -> object:
        if kind == "config":
            return _config(*terms)
        if kind == "proxy_pass":
            return _proxy_pass(mode, terms, kwargs)
        if kind == "cert":
            return CERT[terms[1]]
        raise AssertionError(f"unexpected lookup: {kind} {terms}")

    return env.get_template(TEMPLATE).render(lookup=lookup, domain="ldap.example.com")


def _directives(rendered: str, name: str) -> list[str]:
    return re.findall(rf"^\s*{name}\s+([^;]*);", rendered, re.MULTILINE)


class TestTheListenLine(unittest.TestCase):
    def test_both_modes_listen_on_the_public_ldaps_port_with_tls(self):
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                self.assertEqual(_directives(render(mode), "listen"), ["636 ssl"])


class TestComposeReachesThePublishedLoopbackPort(unittest.TestCase):
    def test_the_compose_render_is_the_former_one_with_a_valid_listen_line(self):
        self.assertEqual(render("compose"), COMPOSE_RENDER)

    def test_compose_sets_no_upstream_variable(self):
        self.assertEqual(_directives(render("compose"), "set"), [])


class TestSwarmReachesSlapdOnTheRelayNetwork(unittest.TestCase):
    def test_swarm_names_the_openldap_service_on_its_internal_port(self):
        self.assertEqual(
            _directives(render("swarm"), "set"),
            ['$proxy_pass_upstream "openldap:389"'],
        )

    def test_swarm_proxies_to_the_variable_so_it_resolves_per_connection(self):
        self.assertEqual(
            _directives(render("swarm"), "proxy_pass"), ["$proxy_pass_upstream"]
        )

    def test_swarm_never_proxies_to_its_own_loopback(self):
        self.assertNotIn("127.0.0.1", render("swarm"))


if __name__ == "__main__":
    unittest.main()
