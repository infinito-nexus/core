from __future__ import annotations

import re
import unittest

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
)

from utils.cache.files import PROJECT_ROOT

PROXY_TEMPLATE = "roles/svc-virt-showroom/templates/proxy.conf.j2"

STUBS = {
    "roles/sys-front-tls/templates/nginx_ssl_header.j2": "SSL_HEADER",
    "roles/sys-front-inj-all/templates/server.conf.j2": "INJECTIONS",
}

DOMAIN = "karakalpakstan.demo.infinito.nexus"


def _render() -> str:
    env = Environment(
        autoescape=True,
        undefined=StrictUndefined,
        loader=ChoiceLoader([DictLoader(STUBS), FileSystemLoader(str(PROJECT_ROOT))]),
    )
    return env.get_template(PROXY_TEMPLATE).render(
        domain=DOMAIN,
        showroom_upstream="192.168.245.10:443",
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
