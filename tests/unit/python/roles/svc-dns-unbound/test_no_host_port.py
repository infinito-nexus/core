from __future__ import annotations

import copy
import os
import re
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLES = PROJECT_ROOT / "roles"
ROLE_DIR = ROLES / "svc-dns-unbound"
SERVICES = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_META_SERVICES)))
COMPOSE = read_text(str(ROLE_DIR / ROLE_FILE_TEMPL_COMPOSE))
HOST_PORT = re.compile(
    r"svc-dns-unbound['\"]\s*,\s*['\"][^'\"]*ports\.(?:local|public)"
)
RESOLVER = ("config", "svc-dns-unbound", "networks.local.dns_resolver")
RESOLVER_ADDRESS = "192.0.2.53"


def consumer_files():
    """Returns:
    ``{path: text}`` of every role file outside svc-dns-unbound that names it.
    """
    found = {}
    for path in iter_project_files(extensions=(".yml", ".j2", ".py")):
        if not path.startswith(f"{ROLES}{os.sep}") or path.startswith(
            f"{ROLE_DIR}{os.sep}"
        ):
            continue
        text = read_text(path)
        if "svc-dns-unbound" in text:
            found[str(Path(path).relative_to(PROJECT_ROOT))] = text
    return found


def host_port_findings(services, compose, consumers):
    """Args:
        services: the parsed ``meta/services.yml`` of svc-dns-unbound.
        compose: the text of its ``templates/compose.yml.j2``.
        consumers: ``{path: text}`` of the role files that name it.

    Returns:
        One message per host-bound port the resolver declares or publishes,
        and per consumer that reads one.
    """
    findings = []
    ports = services["unbound"]["ports"]
    findings += [
        f"ports.{scope} is declared"
        for scope in ("local", "public")
        if ports.get(scope)
    ]
    if "container_ports" in compose:
        findings.append("compose.yml.j2 publishes a port")
    findings += [
        f"{path} reads a host port of svc-dns-unbound"
        for path, text in consumers.items()
        if HOST_PORT.search(text)
    ]
    return findings


class TestNoHostPort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.consumers = consumer_files()

    def test_the_resolver_binds_no_host_port_and_no_consumer_needs_one(self):
        self.assertEqual(host_port_findings(SERVICES, COMPOSE, self.consumers), [])
        self.assertEqual(SERVICES["unbound"]["ports"]["internal"], {"unbound": 53})

    def test_mailu_reaches_the_resolver_on_its_network(self):
        mailu = load_yaml_str(
            read_text(str(ROLES / "web-app-mailu" / ROLE_FILE_VARS_MAIN))
        )
        asked = []
        rendered = (
            Environment(
                undefined=StrictUndefined,
                autoescape=select_autoescape(default_for_string=False),
            )
            .from_string(mailu["MAILU_DNS_RESOLVER"])
            .render(lookup=lambda *terms: asked.append(terms) or RESOLVER_ADDRESS)
        )
        self.assertEqual(rendered, RESOLVER_ADDRESS)
        self.assertEqual(asked, [RESOLVER])
        self.assertIn(f"roles/web-app-mailu/{ROLE_FILE_VARS_MAIN}", self.consumers)

    def test_negative_control_a_declared_local_port_fails(self):
        services = copy.deepcopy(SERVICES)
        services["unbound"]["ports"]["local"] = {"unbound": 53}
        self.assertNotEqual(host_port_findings(services, COMPOSE, {}), [])

    def test_negative_control_a_published_port_fails(self):
        planted = COMPOSE.replace(
            "{{ lookup('container_volumes'",
            "{{ lookup('container_ports', ['unbound', 'unbound']) }}\n"
            "    {{ lookup('container_volumes'",
        )
        self.assertNotEqual(planted, COMPOSE)
        self.assertNotEqual(host_port_findings(SERVICES, planted, {}), [])

    def test_negative_control_a_consumer_of_the_host_port_fails(self):  # nocheck: test.text-presence -- negative control of the repository-wide consumer scan  # fmt: skip
        planted = {
            f"roles/x/{ROLE_FILE_VARS_MAIN}": (
                "X: \"{{ lookup('config', 'svc-dns-unbound', "
                "'services.unbound.ports.local.unbound') }}\""
            )
        }
        self.assertNotEqual(host_port_findings(SERVICES, COMPOSE, planted), [])


if __name__ == "__main__":
    unittest.main()
