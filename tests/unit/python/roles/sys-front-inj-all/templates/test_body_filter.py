"""The body filter of a vhost serves the snippets rendered for that vhost and
rewrites no deployment host at request time."""

from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.mirror_filters import FilterModule as MirrorFilters
from plugins.filter.network_of import FilterModule as NetworkFilters
from utils.domains.default_primary import default_domain_primary
from utils.networks.reachability import network_of

from . import PROJECT_ROOT

TEMPLATE = "roles/sys-front-inj-all/templates/body_filter.lua.j2"
PRIMARY = default_domain_primary()
NODE = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
EXTERNAL = "assets.example.net"
CDN = {"clearnet": f"https://cdn.{PRIMARY}", "tor": f"http://cdn.{NODE}"}
MIRROR = {"clearnet": f"https://mirror.{PRIMARY}", "tor": f"http://mirror.{NODE}"}
APPLICATIONS = {
    "web-app-x": {
        "services": {"tor": {"enabled": True}},
        "csp": {"whitelist": {"script-src-elem": [f"https://{EXTERNAL}"]}},
    },
    "svc-net-tor": {"services": {"tor": {"node": NODE}}},
}


def _config(app: str, path: str, default):
    node = APPLICATIONS.get(app, {})
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def render(domain: str) -> str:
    """Return the body filter Lua of one vhost of ``web-app-x`` on a multi node.

    Args:
        domain: the vhost domain; its network picks the provider URLs the
            ``tls`` lookup aligns to, as the real lookup does with ``domain``
            in scope.
    """
    network = network_of(domain)

    def lookup(kind, *args, **_kw):
        if kind == "applications":
            return APPLICATIONS
        if kind == "config":
            return _config(*args)
        if kind == "tls":
            return {"web-svc-cdn": CDN, "web-svc-mirror": MIRROR}[args[0]][network]
        if kind == "network_urls":
            return list(CDN.values())
        raise AssertionError(f"unexpected lookup {kind!r}")

    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters.update(NetworkFilters().filters())
    env.filters.update(MirrorFilters().filters())
    env.filters["bool"] = bool
    env.filters["regex_replace"] = lambda value, pattern, repl: re.sub(
        pattern, repl, value
    )
    env.tests["search"] = lambda value, pattern: re.search(pattern, value) is not None
    return env.get_template(TEMPLATE).render(
        application_id="web-app-x",
        domain=domain,
        lookup=lookup,
        DOMAIN_PRIMARY=PRIMARY,
        inj_enabled={},
        inj_top_features=[],
        inj_head_features=[],
        inj_body_features=[],
    )


class TestBodyFilter(unittest.TestCase):
    def test_no_vhost_rewrites_the_cdn_origin_at_request_time(self) -> None:
        for domain in (f"x.{PRIMARY}", f"x.{NODE}"):
            with self.subTest(domain=domain):
                rendered = render(domain)
                self.assertNotIn("http_host", rendered)
                self.assertNotIn("cdn.", rendered)

    def test_an_onion_vhost_still_maps_external_assets_to_its_mirror(self) -> None:
        self.assertIn(f"{MIRROR['tor']}/{EXTERNAL}", render(f"x.{NODE}"))

    def test_a_clearnet_vhost_maps_no_external_asset(self) -> None:
        self.assertNotIn(EXTERNAL, render(f"x.{PRIMARY}"))


if __name__ == "__main__":
    unittest.main()
