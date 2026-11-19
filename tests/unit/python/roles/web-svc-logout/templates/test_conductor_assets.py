from __future__ import annotations

import re
import unittest
from unittest.mock import MagicMock, patch

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from plugins.lookup import asset as asset_mod
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.networks.instances import labelled
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

APP = "web-svc-logout"
ROLE = PROJECT_ROOT / "roles" / APP
VHOST = f"roles/{APP}/templates/proxy.conf.j2"
CDN = "https://cdn.example.test"
STUBS = {
    "roles/sys-svc-proxy/templates/vhost/basic.conf.j2": "{{ webserver_extra_configuration }}",
    "roles/sys-svc-proxy/templates/headers/forwarded_base.conf.j2": "",
    "roles/sys-svc-proxy/templates/headers/identity_request_strips.conf.j2": "",
    "roles/sys-svc-proxy/templates/headers/upstream_strips.conf.j2": "",
}
SUB_FILTER = re.compile(r"^\s*sub_filter '([^']*)' '([^']*)';", re.MULTILINE)
SUB_FILTER_ONCE_OFF = re.compile(r"^\s*sub_filter_once off;", re.MULTILINE)


def role_vars() -> dict:
    return load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))


def upstream_conductor() -> str:
    """Returns:
    The asset tags of the conductor page the pinned universal-logout image
    serves, both under the prefix the role declares as upstream.
    """
    prefix = role_vars()["LOGOUT_CONDUCTOR_BOOTSTRAP_UPSTREAM"]
    return (
        f'<link href="{prefix}dist/css/bootstrap.min.css" rel="stylesheet" />\n'
        f'<script src="{prefix}dist/js/bootstrap.bundle.min.js"></script>\n'
    )


def asset_lookup(*terms) -> str:
    """Resolve lookup('asset') against the role's committed lockfile.

    Args:
        terms: application id, package and path within the package.
    """
    module = asset_mod.LookupModule.__new__(asset_mod.LookupModule)
    module._loader = MagicMock()
    module._templar = MagicMock(available_variables={})
    with patch.object(asset_mod, "resolve_host", return_value=CDN):
        return module.run(list(terms), variables={"group_names": [APP]})[0]


def lookup(name, *terms, **kwargs):
    """
    Args:
        name: the lookup plugin.
        terms: its positional terms.
        kwargs: its keyword arguments.
    """
    if name == "asset":
        return asset_lookup(*terms)
    if name == "config":
        return 8048
    if name == "proxy_pass":
        return "proxy_pass http://logout;"
    raise AssertionError(f"unexpected lookup: {name} {terms} {kwargs}")


def render_vhost() -> str:
    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        loader=ChoiceLoader([DictLoader(STUBS), FileSystemLoader(str(PROJECT_ROOT))]),
        undefined=StrictUndefined,
        trim_blocks=True,
    )
    env.filters.update(labelled=labelled, network_of=lambda _domain: "clearnet")
    env.globals["lookup"] = lookup
    return env.get_template(VHOST).render(
        application_id=APP,
        domain="logout.example.test",
        proxy_internal_port=8000,
        LOGOUT_INSTANCES=[{"label": "", "network": "clearnet"}],
        LOGOUT_CONDUCTOR_BOOTSTRAP_UPSTREAM=role_vars()[
            "LOGOUT_CONDUCTOR_BOOTSTRAP_UPSTREAM"
        ],
    )


def served_conductor(vhost: str) -> str:
    """Apply the vhost's sub_filter rules to the upstream conductor as nginx does.

    Args:
        vhost: the rendered vhost configuration.
    """
    body = upstream_conductor()
    count = -1 if SUB_FILTER_ONCE_OFF.search(vhost) else 1
    for search, replacement in SUB_FILTER.findall(vhost):
        body = body.replace(search, replacement, count)
    return body


class TestConductorAssets(unittest.TestCase):
    def test_the_conductor_loads_bootstrap_from_the_internal_cdn(self) -> None:
        body = served_conductor(render_vhost())
        self.assertNotIn(
            "cdn.jsdelivr.net",
            body,
            "Keycloak's front-channel logout page redirects only once its conductor "
            "iframe has loaded, so a blocked external CDN holds every logout for the "
            "browser's connect timeout",
        )
        base = asset_lookup(APP, "bootstrap", "")
        self.assertTrue(base.startswith(f"{CDN}/npm/bootstrap@"), base)
        self.assertIn(f'href="{base}dist/css/bootstrap.min.css"', body)
        self.assertIn(f'src="{base}dist/js/bootstrap.bundle.min.js"', body)


if __name__ == "__main__":
    unittest.main()
