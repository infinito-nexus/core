from __future__ import annotations

import importlib.util
import unittest

from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.filter.network_of import in_network
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.networks.reachability import network_of
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles" / "web-app-nextcloud"
VARS = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_VARS_MAIN)))
ADDON = load_yaml_str(read_text(str(ROLE_DIR / "meta" / "addons" / "user_oidc.yml")))
ONION = "next.cloud." + "a" * 56 + ".onion"
CLEARNET = "next.cloud.infinito.example"
KEY = "allow_insecure_http"


def _plugin_config_filters():
    path = ROLE_DIR / "filter_plugins" / "nextcloud_plugin_config.py"
    spec = importlib.util.spec_from_file_location("nextcloud_plugin_config", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sibling_lookup(family: list[str]):
    """
    Args:
        family: the network siblings of the Nextcloud domain, canonical first.

    Returns:
        A ``lookup`` stand-in that answers ``network_siblings`` of the
        canonical domain with ``family`` and refuses every other call.
    """

    def lookup(name, domain):
        if name != "network_siblings" or domain != family[0]:
            raise AssertionError(f"unexpected lookup({name!r}, {domain!r})")
        return list(family)

    return lookup


def _environment(family: list[str]) -> Environment:
    """
    Args:
        family: the network siblings of the Nextcloud domain, canonical first.

    Returns:
        A Jinja environment with the filters and the ``lookup`` the
        expressions under test use.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = lambda value: boolean(value, strict=False)
    env.filters["network_of"] = network_of
    env.filters["in_network"] = in_network
    env.globals["lookup"] = _sibling_lookup(family)
    return env


def _entry() -> dict:
    entries = [
        item
        for item in ADDON["config"].get("plugin_configuration", [])
        if item["appid"] == "user_oidc" and item["configkey"] == KEY
    ]
    if len(entries) != 1:
        raise AssertionError(
            f"meta/addons/user_oidc.yml declares {KEY} {len(entries)} times"
        )
    return entries[0]


def _allowed(*, family: list[str], protocol: str) -> bool:
    """
    Args:
        family: the network siblings of the Nextcloud domain, canonical first.
        protocol: the web protocol the canonical domain serves Nextcloud on.

    Returns:
        What ``NEXTCLOUD_USER_OIDC_ALLOW_INSECURE_HTTP`` renders to.
    """
    rendered = (
        _environment(family)
        .from_string(VARS["NEXTCLOUD_USER_OIDC_ALLOW_INSECURE_HTTP"])
        .render(NEXTCLOUD_DOMAIN=family[0], NEXTCLOUD_PROTOCOL=protocol)
    )
    return boolean(rendered, strict=True)


def _occ_argv(*, family: list[str], protocol: str) -> list[str]:
    """
    Args:
        family: the network siblings of the Nextcloud domain, canonical first.
        protocol: the web protocol the canonical domain serves Nextcloud on.

    Returns:
        The ``occ`` arguments the batched plugin configuration runs for the entry.
    """
    entry = dict(_entry())
    entry["configvalue"] = (
        _environment(family)
        .from_string(entry["configvalue"])
        .render(
            NEXTCLOUD_USER_OIDC_ALLOW_INSECURE_HTTP=_allowed(
                family=family, protocol=protocol
            )
        )
    )
    filters = _plugin_config_filters()
    pending = filters.nextcloud_plugin_config_pending(
        [{"config": {"plugin_configuration": [entry]}}], {"apps": {}}
    )
    batch = filters.nextcloud_occ_config_set_batch(pending)
    if len(batch) != 1:
        raise AssertionError(f"expected one occ call, got {batch!r}")
    return batch[0]["argv"]


class TestUserOidcInsecureHttp(unittest.TestCase):
    def test_a_plain_http_onion_turns_the_setting_on(self):
        self.assertTrue(
            _allowed(family=[ONION], protocol="http"),
            "user_oidc answers every sign-in on plain HTTP with a throttled 404",
        )

    def test_an_onion_sibling_of_a_clearnet_https_deployment_turns_the_setting_on(
        self,
    ):
        self.assertTrue(
            _allowed(family=[CLEARNET, ONION], protocol="https"),
            "the onion sibling of a multi-network node serves Nextcloud on plain "
            "HTTP, so user_oidc answers its sign-in with a throttled 404",
        )

    def test_an_onion_sibling_of_a_clearnet_plain_http_deployment_turns_the_setting_on(
        self,
    ):
        self.assertTrue(
            _allowed(family=[CLEARNET, ONION], protocol="http"),
            "the setting is app-wide: a TLS-off node with Tor needs it for the "
            "onion sign-in, and serves Keycloak on plain HTTP as well",
        )

    def test_a_clearnet_https_deployment_keeps_the_guard(self):
        self.assertFalse(_allowed(family=[CLEARNET], protocol="https"))

    def test_a_clearnet_plain_http_deployment_keeps_the_guard(self):
        self.assertFalse(
            _allowed(family=[CLEARNET], protocol="http"),
            "only Tor encrypts a plain-HTTP hop, so clearnet HTTP must stay refused",
        )

    def test_the_entry_is_written_as_a_boolean(self):
        self.assertEqual(str(_entry()["type"]), "boolean")

    def test_the_onion_writes_the_setting_on(self):
        argv = _occ_argv(family=[ONION], protocol="http")
        self.assertEqual(argv[:3], ["config:app:set", "user_oidc", KEY])
        self.assertIn("--type=boolean", argv)
        self.assertIn("--value=1", argv)

    def test_a_multi_network_node_writes_the_setting_on(self):
        argv = _occ_argv(family=[CLEARNET, ONION], protocol="https")
        self.assertIn("--type=boolean", argv)
        self.assertIn("--value=1", argv)

    def test_clearnet_writes_the_setting_off(self):
        argv = _occ_argv(family=[CLEARNET], protocol="https")
        self.assertIn("--type=boolean", argv)
        self.assertIn("--value=0", argv)
        self.assertNotIn("--value=1", argv)


if __name__ == "__main__":
    unittest.main()
