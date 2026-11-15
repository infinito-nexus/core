from __future__ import annotations

import re
import unittest
from unittest.mock import MagicMock, patch

from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from plugins.lookup.container_extra_hosts import LookupModule as ExtraHosts
from plugins.lookup.tor_socks_proxy import resolve_proxy_url
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles/svc-net-tor-smtp"
COMPOSE = ROLE / ROLE_FILE_TEMPL_COMPOSE
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
SERVICES = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
APPLICATIONS = {
    "svc-net-tor": {
        "services": load_yaml_any(
            str(PROJECT_ROOT / "roles/svc-net-tor" / ROLE_FILE_META_SERVICES)
        )
    }
}
INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
    "roles/sys-svc-container/templates/base.yml.j2": "",
}
MODES = ("compose", "swarm")


def _environment() -> Environment:
    environment = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        loader=DictLoader(INCLUDES),
    )
    environment.filters["regex_replace"] = lambda value, pattern, repl: re.sub(
        pattern, repl, value
    )
    return environment


def _socks_host() -> str:
    environment = _environment()
    environment.globals["lookup"] = lambda name: {
        "tor_socks_proxy": resolve_proxy_url(APPLICATIONS)
    }[name]
    socks = environment.from_string(VARS["TOR_SMTP_SOCKS"]).render()
    return environment.from_string(VARS["TOR_SMTP_SOCKS_HOST"]).render(
        TOR_SMTP_SOCKS=socks
    )


def _role_lookup(name: str, *_args, **_kwargs) -> MagicMock:
    if name != "config":
        raise AssertionError(f"unexpected lookup {name!r}")
    plugin = MagicMock()
    plugin.run.side_effect = lambda terms, variables=None, **_: [
        bool((SERVICES.get(terms[1].split(".")[1]) or {}).get("enabled", False))
    ]
    return plugin


def _service(mode: str) -> dict:
    variables = {
        "application_id": "svc-net-tor-smtp",
        "DEPLOYMENT_MODE": mode,
        "TOR_SMTP_IMAGE": SERVICES["tor-smtp"]["image"],
        "TOR_SMTP_VERSION": SERVICES["tor-smtp"]["version"],
        "TOR_SMTP_CONTAINER": SERVICES["tor-smtp"]["name"],
    }

    def lookup(name: str, *_terms, **kwargs) -> str:
        if name == "container_extra_hosts":
            with patch(
                "plugins.lookup.container_extra_hosts.lookup_loader.get",
                side_effect=_role_lookup,
            ):
                return ExtraHosts().run(None, variables=variables, **kwargs)[0]
        if name == "template":
            return "build:\n  context: ."
        return ""

    environment = _environment()
    environment.globals["lookup"] = lookup
    rendered = environment.from_string(read_text(str(COMPOSE))).render(**variables)
    return load_yaml_str(rendered)["services"]["tor-smtp"]


class TestComposeSocksHost(unittest.TestCase):
    def test_the_socks_host_points_at_the_node_in_every_mode(self) -> None:
        host = _socks_host()
        for mode in MODES:
            with self.subTest(mode=mode):
                self.assertEqual(
                    _service(mode).get("extra_hosts"), [f"{host}:host-gateway"]
                )


if __name__ == "__main__":
    unittest.main()
