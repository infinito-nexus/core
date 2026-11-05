"""The stream block of the front proxy resolves upstream names in swarm.

A stream server that proxies to a variable looks the name up per connection
through the ``resolver`` of ``stream{}``; the one of ``http{}`` does not reach
it. Compose keeps the stream block it had.
"""

from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.on_off import on_off
from utils.cache.yaml import load_yaml

from . import PROJECT_ROOT

TEMPLATE = "roles/sys-svc-webserver-core/templates/nginx.conf.j2"
STREAMS_DIR = "/etc/openresty/streams/"
NETWORKS = load_yaml(str(PROJECT_ROOT / "group_vars/all/08_networks.yml"))
RESOLVER = NETWORKS["NETWORK_DOCKER_EMBEDDED_DNS_RESOLVER"]
COMPOSE_STREAM_BLOCK = f"stream{{\n  include {STREAMS_DIR}*.conf;\n}}\n"


def _directive() -> str:
    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.filters["on_off"] = on_off
    return env.from_string(NETWORKS["NETWORK_DOCKER_DNS_NGINX_DIRECTIVE"]).render(
        **NETWORKS
    )


def render(swarm: bool, directive: str | None = None) -> str:
    """Render nginx.conf the way Ansible's template module does.

    Args:
        swarm: the value of IS_SWARM_MODE.
        directive: the value of NETWORK_DOCKER_DNS_NGINX_DIRECTIVE; the one
            group_vars renders when None.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["bool"] = bool

    def lookup(kind: str, *terms: str) -> object:
        if kind == "nginx" and terms == ("directories.configuration.streams",):
            return STREAMS_DIR
        if kind == "nginx" and terms == ("directories.configuration.http_includes",):
            return ["/etc/openresty/http/"]
        if kind == "nginx":
            return f"/var/lib/openresty/{terms[0]}"
        if kind == "debug":
            return False
        raise AssertionError(f"unexpected lookup: {kind} {terms}")

    return env.get_template(TEMPLATE).render(
        IS_SWARM_MODE=swarm,
        NETWORK_DOCKER_DNS_NGINX_DIRECTIVE=directive or _directive(),
        WEBSERVER_PROXY_WORKER_PROCESSES=1,
        WEBSERVER_PROXY_WORKER_CONNECTIONS=256,
        WEBSERVER_PROXY_WORKER_RLIMIT_NOFILE=512,
        lookup=lookup,
    )


def _stream_block(rendered: str) -> str:
    return rendered[rendered.index("stream{") :]


def _resolvers(block: str) -> list[str]:
    return re.findall(r"^\s*resolver\s+([^;]*);", block, re.MULTILINE)


class TestStreamResolver(unittest.TestCase):
    def test_swarm_resolves_through_the_docker_embedded_dns(self):
        self.assertEqual(
            _resolvers(_stream_block(render(True))),
            [f"{RESOLVER} valid=30s ipv6=off"],
        )

    def test_swarm_reuses_the_shared_docker_dns_directive(self):
        sentinel = "resolver 192.0.2.53 valid=5s ipv6=on;"
        self.assertEqual(
            _resolvers(_stream_block(render(True, sentinel))),
            ["192.0.2.53 valid=5s ipv6=on"],
        )

    def test_swarm_keeps_including_the_stream_servers(self):
        self.assertIn(f"include {STREAMS_DIR}*.conf;", _stream_block(render(True)))

    def test_compose_keeps_its_former_stream_block(self):
        self.assertEqual(_stream_block(render(False)), COMPOSE_STREAM_BLOCK)

    def test_compose_has_no_resolver_at_all(self):
        self.assertEqual(_resolvers(render(False)), [])


if __name__ == "__main__":
    unittest.main()
