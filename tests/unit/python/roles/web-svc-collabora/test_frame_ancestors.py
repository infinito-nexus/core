from __future__ import annotations

import json
import sys
import unittest
import unittest.mock as mock

from jinja2 import Environment, StrictUndefined, select_autoescape

import utils.tls.common as _tls_common
from plugins.filter.csp_filters import FilterModule
from plugins.lookup.network_urls import LookupModule as NetworkUrlsLookup
from plugins.lookup.tls import LookupModule as TlsLookup
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

sys.modules.setdefault("ansible.module_utils.tls_common", _tls_common)

EXTRAS = PROJECT_ROOT / "roles/web-svc-collabora/templates/csp/extras.yml.j2"
PRIMARY = "example"
NODE = "a" * 56 + ".onion"
NEXTCLOUD = "next.cloud." + PRIMARY
NEXTCLOUD_ONION = "next.cloud." + NODE
COLLABORA = "collabora." + PRIMARY
COLLABORA_ONION = "collabora." + NODE
MULTI_DOMAINS = {
    "web-app-nextcloud": [NEXTCLOUD, NEXTCLOUD_ONION],
    "web-svc-collabora": [COLLABORA, COLLABORA_ONION],
    "web-svc-cdn": ["cdn." + PRIMARY, "cdn." + NODE],
}


def frame_ancestors(domains):
    variables = {
        "domains": domains,
        "applications": {},
        "TLS_ENABLED": True,
        "TLS_MODE": "letsencrypt",
        "application_id": "web-svc-collabora",
        "DOMAIN_PRIMARY": PRIMARY,
        "group_names": ["svc-net-tor"],
    }
    tls = TlsLookup()
    tls._loader = mock.MagicMock()
    network_urls = NetworkUrlsLookup()

    def _tls_loader(name, *_args, **_kwargs):
        return mock.MagicMock(
            run=lambda _terms, variables=None, **_: [(variables or {}).get(name, {})]
        )

    def _network_urls_loader(name, *_args, **_kwargs):
        if name == "domains":
            return mock.MagicMock(run=lambda terms, variables=None, **_: [domains])
        if name == "config":
            return mock.MagicMock(run=lambda terms, variables=None, **_: [NODE])
        if name == "tls":
            return mock.MagicMock(
                run=lambda terms, variables=None, **_: tls.run(
                    list(terms), variables=variables
                )
            )
        raise AssertionError(f"network_urls calls an unexpected lookup: {name!r}")

    def lookup(name, *terms):
        if name == "domain":
            return domains[terms[0]][0]
        if name == "tls":
            return tls.run(list(terms), variables=variables)[0]
        if name == "network_urls":
            return network_urls.run(list(terms), variables=variables)[0]
        raise AssertionError(f"the expression calls an unexpected lookup: {name!r}")

    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["to_json"] = json.dumps
    with (
        mock.patch("plugins.lookup.tls.lookup_loader") as tls_loader,
        mock.patch("plugins.lookup.network_urls.lookup_loader") as urls_loader,
    ):
        tls_loader.get.side_effect = _tls_loader
        urls_loader.get.side_effect = _network_urls_loader
        rendered = environment.from_string(read_text(str(EXTRAS))).render(lookup=lookup)
    return load_yaml_str(rendered)["frame-ancestors"]


def ancestors_of(vhost, extra):
    applications = {
        "web-svc-collabora": {
            "csp": {"whitelist": {"frame-ancestors": ["*." + PRIMARY]}}
        },
        "svc-net-tor": {"services": {"tor": {"node": NODE}}},
    }
    header = FilterModule().build_csp_header(
        applications,
        "web-svc-collabora",
        MULTI_DOMAINS,
        "https",
        extra_whitelist={"frame-ancestors": extra} if extra else None,
        domain_primary=PRIMARY,
        vhost_domain=vhost,
    )
    for raw in header.split(";"):
        part = raw.strip()
        if part.startswith("frame-ancestors "):
            return part.split(" ")[1:]
    raise AssertionError(f"no frame-ancestors in {header!r}")


class TestFrameAncestors(unittest.TestCase):
    def test_every_nextcloud_sibling_with_its_own_scheme(self):
        self.assertEqual(
            frame_ancestors(MULTI_DOMAINS),
            [f"https://{NEXTCLOUD}", f"http://{NEXTCLOUD_ONION}"],
        )

    def test_a_clearnet_only_nextcloud(self):
        domains = {
            "web-app-nextcloud": [NEXTCLOUD],
            "web-svc-collabora": [COLLABORA],
        }
        self.assertEqual(frame_ancestors(domains), [f"https://{NEXTCLOUD}"])

    def test_a_tor_only_nextcloud(self):
        domains = {
            "web-app-nextcloud": [NEXTCLOUD_ONION],
            "web-svc-collabora": [COLLABORA_ONION],
        }
        self.assertEqual(frame_ancestors(domains), [f"http://{NEXTCLOUD_ONION}"])

    def test_the_clearnet_editor_admits_the_onion_nextcloud_page(self):
        union = frame_ancestors(MULTI_DOMAINS)
        self.assertNotIn(f"http://{NEXTCLOUD_ONION}", ancestors_of(COLLABORA, None))
        ancestors = ancestors_of(COLLABORA, union)
        self.assertIn(f"http://{NEXTCLOUD_ONION}", ancestors)
        self.assertIn(f"https://{NEXTCLOUD}", ancestors)
        self.assertIn("*." + PRIMARY, ancestors)

    def test_the_onion_editor_translates_the_clearnet_sibling_away(self):
        ancestors = ancestors_of(COLLABORA_ONION, frame_ancestors(MULTI_DOMAINS))
        self.assertEqual(ancestors.count(f"http://{NEXTCLOUD_ONION}"), 1)
        self.assertNotIn(f"https://{NEXTCLOUD}", ancestors)


if __name__ == "__main__":
    unittest.main()
