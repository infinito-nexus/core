from __future__ import annotations

import importlib.util
import unittest

from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment, StrictUndefined, select_autoescape

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


def _environment() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = lambda value: boolean(value, strict=False)
    env.filters["network_of"] = network_of
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


def _allowed(*, domain: str, protocol: str) -> bool:
    """
    Args:
        domain: the Nextcloud domain of the deployment.
        protocol: the web protocol the deployment serves Nextcloud on.

    Returns:
        What ``NEXTCLOUD_USER_OIDC_ALLOW_INSECURE_HTTP`` renders to.
    """
    rendered = (
        _environment()
        .from_string(VARS["NEXTCLOUD_USER_OIDC_ALLOW_INSECURE_HTTP"])
        .render(NEXTCLOUD_DOMAIN=domain, NEXTCLOUD_PROTOCOL=protocol)
    )
    return boolean(rendered, strict=True)


def _occ_argv(*, domain: str, protocol: str) -> list[str]:
    """
    Args:
        domain: the Nextcloud domain of the deployment.
        protocol: the web protocol the deployment serves Nextcloud on.

    Returns:
        The ``occ`` arguments the batched plugin configuration runs for the entry.
    """
    entry = dict(_entry())
    entry["configvalue"] = (
        _environment()
        .from_string(entry["configvalue"])
        .render(
            NEXTCLOUD_USER_OIDC_ALLOW_INSECURE_HTTP=_allowed(
                domain=domain, protocol=protocol
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
            _allowed(domain=ONION, protocol="http"),
            "user_oidc answers every sign-in on plain HTTP with a throttled 404",
        )

    def test_a_clearnet_https_deployment_keeps_the_guard(self):
        self.assertFalse(_allowed(domain=CLEARNET, protocol="https"))

    def test_a_clearnet_plain_http_deployment_keeps_the_guard(self):
        self.assertFalse(
            _allowed(domain=CLEARNET, protocol="http"),
            "only Tor encrypts a plain-HTTP hop, so clearnet HTTP must stay refused",
        )

    def test_the_entry_is_written_as_a_boolean(self):
        self.assertEqual(str(_entry()["type"]), "boolean")

    def test_the_onion_writes_the_setting_on(self):
        argv = _occ_argv(domain=ONION, protocol="http")
        self.assertEqual(argv[:3], ["config:app:set", "user_oidc", KEY])
        self.assertIn("--type=boolean", argv)
        self.assertIn("--value=1", argv)

    def test_clearnet_writes_the_setting_off(self):
        argv = _occ_argv(domain=CLEARNET, protocol="https")
        self.assertIn("--type=boolean", argv)
        self.assertIn("--value=0", argv)
        self.assertNotIn("--value=1", argv)


if __name__ == "__main__":
    unittest.main()
