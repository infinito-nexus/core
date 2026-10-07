from __future__ import annotations

import sys
import unittest
import unittest.mock as mock
from unittest.mock import patch

from jinja2 import Environment, StrictUndefined, select_autoescape

import utils.tls_common as _tls_common
from plugins.lookup.tls import LookupModule
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

sys.modules.setdefault("ansible.module_utils.tls_common", _tls_common)

VARS = PROJECT_ROOT / "roles/web-svc-collabora" / ROLE_FILE_VARS_MAIN
NEXTCLOUD_ONION = "next.cloud." + "a" * 56 + ".onion"
COLLABORA_ONION = "collabora." + "a" * 56 + ".onion"


def wopi_host(domains: dict[str, list[str]]) -> str:
    variables = {
        "domains": domains,
        "applications": {},
        "TLS_ENABLED": True,
        "TLS_MODE": "letsencrypt",
        "application_id": "web-svc-collabora",
    }
    tls = LookupModule()
    tls._loader = mock.MagicMock()

    def _get(name, *_args, **_kwargs):
        return mock.MagicMock(
            run=lambda _terms, variables=None, **_: [(variables or {}).get(name, {})]
        )

    def lookup(name, *terms):
        if name == "domain":
            return domains[terms[0]][0]
        if name == "tls":
            return tls.run(list(terms), variables=variables)[0]
        raise AssertionError(f"the expression calls an unexpected lookup: {name!r}")

    expression = load_yaml_str(read_text(str(VARS)))["COLLABORA_WOPI_HOST"]
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    with patch("plugins.lookup.tls.lookup_loader") as loader:
        loader.get.side_effect = _get
        return env.from_string(expression).render(lookup=lookup)


class TestWopiHost(unittest.TestCase):
    def test_an_onion_primary_nextcloud_beside_a_clearnet_collabora(self):
        self.assertEqual(
            wopi_host(
                {
                    "web-app-nextcloud": [NEXTCLOUD_ONION, "next.cloud.example"],
                    "web-svc-collabora": ["collabora.example"],
                }
            ),
            f"http://{NEXTCLOUD_ONION}:80",
        )

    def test_both_apps_behind_tor(self):
        self.assertEqual(
            wopi_host(
                {
                    "web-app-nextcloud": [NEXTCLOUD_ONION],
                    "web-svc-collabora": [COLLABORA_ONION],
                }
            ),
            f"http://{NEXTCLOUD_ONION}:80",
        )

    def test_both_apps_on_clearnet(self):
        self.assertEqual(
            wopi_host(
                {
                    "web-app-nextcloud": ["next.cloud.example"],
                    "web-svc-collabora": ["collabora.example"],
                }
            ),
            "https://next.cloud.example:443",
        )


if __name__ == "__main__":
    unittest.main()
