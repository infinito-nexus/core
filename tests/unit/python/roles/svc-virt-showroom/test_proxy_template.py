from __future__ import annotations

import re
import runpy
import unittest

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
)

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVER

PROXY_TEMPLATE = "roles/svc-virt-showroom/templates/proxy.conf.j2"
FILTERS = PROJECT_ROOT / "roles/svc-virt-showroom/filter_plugins/showroom.py"
SERVER = PROJECT_ROOT / "roles/svc-virt-showroom" / ROLE_FILE_META_SERVER
CORE = PROJECT_ROOT / "roles/svc-virt-showroom/tasks/00_core.yml"
STACK_VHOSTS = PROJECT_ROOT / "roles/svc-stack/filter_plugins/stack_vhosts.py"
FRONT_ENTRY = {"name": "svc-stack", "tasks_from": "consumer/front.yml"}

STUBS = {
    "roles/sys-front-tls/templates/nginx_ssl_header.j2": "SSL_HEADER",
    "roles/sys-front-inj-all/templates/server.conf.j2": "INJECTIONS",
}

DOMAIN = "karakalpakstan.demo.infinito.nexus"
PROJECTS = {
    "karakalpak": {
        "address": "192.168.245.10",
        "domains": [DOMAIN, f"auth.{DOMAIN}"],
    },
    "lab": {"address": "192.168.245.11", "domains": ["lab.demo.infinito.nexus"]},
}
UPSTREAMS = {
    DOMAIN: "192.168.245.10:443",
    f"auth.{DOMAIN}": "192.168.245.10:443",
    "lab.demo.infinito.nexus": "192.168.245.11:443",
}


def _render(domain: str = DOMAIN) -> str:
    env = Environment(
        autoescape=True,
        undefined=StrictUndefined,
        loader=ChoiceLoader([DictLoader(STUBS), FileSystemLoader(str(PROJECT_ROOT))]),
    )
    env.filters["showroom_vhosts"] = runpy.run_path(str(FILTERS))["vhosts"]
    return env.get_template(PROXY_TEMPLATE).render(
        domain=domain,
        SHOWROOM_PROJECTS=PROJECTS,
        webserver_client_max_body_size="100m",
    )


def _directives(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


class TestShowroomProxyTemplate(unittest.TestCase):
    def setUp(self) -> None:
        self.rendered = _render()
        self.directives = _directives(self.rendered)

    def test_serves_the_domain_with_the_host_certificate(self) -> None:
        self.assertIn(f"server_name {DOMAIN};", self.directives)
        self.assertIn("SSL_HEADER", self.directives)

    def test_forwards_to_port_443_of_the_project_server(self) -> None:
        self.assertIn("proxy_pass https://192.168.245.10:443;", self.directives)

    def test_every_domain_forwards_to_the_server_of_its_own_project(self) -> None:
        for domain, upstream in UPSTREAMS.items():
            with self.subTest(domain=domain):
                self.assertIn(
                    f"proxy_pass https://{upstream};", _directives(_render(domain))
                )

    def test_the_meta_serves_every_canonical_domain(self) -> None:
        stack_vhosts = runpy.run_path(str(STACK_VHOSTS))["stack_vhosts"]
        declared = (load_yaml_str(read_text(SERVER)) or {}).get("vhosts") or {}
        canonical = sorted(UPSTREAMS)

        self.assertEqual(
            [
                vhost["domain"]
                for vhost in stack_vhosts(declared, canonical[0], canonical)
            ],
            canonical,
        )

    def test_a_showroom_without_projects_serves_no_vhost(self) -> None:
        [front] = [
            task
            for task in load_yaml_str(read_text(CORE)) or []
            if task.get("ansible.builtin.include_role") == FRONT_ENTRY
        ]
        serves = Environment(autoescape=True).compile_expression(front["when"])

        self.assertFalse(serves(SHOWROOM_CANONICAL_DOMAINS=[]))
        self.assertTrue(serves(SHOWROOM_CANONICAL_DOMAINS=[DOMAIN]))

    def test_hands_the_original_host_name_to_the_upstream_tls(self) -> None:
        self.assertIn("proxy_ssl_server_name on;", self.directives)
        self.assertIn("proxy_ssl_name $host;", self.directives)
        self.assertIn("proxy_ssl_verify off;", self.directives)

    def test_keeps_the_original_host_header_once(self) -> None:
        host_headers = [
            line
            for line in self.directives
            if re.match(r"proxy_set_header Host\b", line)
        ]
        self.assertEqual(["proxy_set_header Host $host;"], host_headers)

    def test_upgrades_websockets(self) -> None:
        self.assertIn("proxy_http_version 1.1;", self.directives)
        self.assertIn("proxy_set_header Upgrade $proxy_upgrade;", self.directives)
        self.assertIn(
            "proxy_set_header Connection $connection_upgrade;", self.directives
        )

    def test_strips_client_supplied_identity_headers(self) -> None:
        self.assertIn('proxy_set_header X-Forwarded-User "";', self.directives)


if __name__ == "__main__":
    unittest.main()
