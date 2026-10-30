from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-espocrm"
CLEARNET = "https://espo.crm.example.test/"
ONION = "http://espo.crm." + "a" * 56 + ".onion/"


def _sibling_site_urls(network_urls: list[str]) -> list[str]:
    """
    Args:
        network_urls: the answer of lookup('network_urls', ESPOCRM_URL) on the host.

    Returns:
        ESPOCRM_SIBLING_SITE_URLS as vars/main.yml resolves it.
    """

    def lookup(*terms: str) -> list[str]:
        if terms != ("network_urls", CLEARNET):
            raise AssertionError(f"the sibling URLs render an unexpected lookup{terms}")
        return network_urls

    expression = load_yaml(ROLE / ROLE_FILE_VARS_MAIN)["ESPOCRM_SIBLING_SITE_URLS"]
    return Environment(
        undefined=StrictUndefined, autoescape=select_autoescape()
    ).compile_expression(expression.strip().removeprefix("{{").removesuffix("}}"))(
        lookup=lookup, ESPOCRM_URL=CLEARNET
    )


def _render(network_urls: list[str]) -> str:
    """
    Args:
        network_urls: the answer of lookup('network_urls', ESPOCRM_URL) on the host.

    Returns:
        data/config-override.php as the deploy writes it.
    """
    env = Environment(
        loader=FileSystemLoader(str(ROLE / "templates")),
        undefined=StrictUndefined,
        trim_blocks=True,
        keep_trailing_newline=True,
        autoescape=select_autoescape(),
    )
    return env.get_template("config-override.php.j2").render(
        ESPOCRM_SIBLING_SITE_URLS=_sibling_site_urls(network_urls)
    )


def _answered(php: str) -> list[str]:
    return re.findall(r"^    '([^']+)',$", php, re.MULTILINE)


class TestConfigOverride(unittest.TestCase):
    def test_the_onion_sibling_is_answered_with_its_plaintext_base_url(self) -> None:
        self.assertEqual(
            _answered(_render([CLEARNET, ONION])),
            [ONION],
            "EspoCRM builds the OIDC redirect_uri from siteUrl, so an onion login "
            "returns to the clearnet callback unless the onion host answers its own URL",
        )

    def test_the_canonical_host_keeps_the_stored_site_url(self) -> None:
        self.assertNotIn(CLEARNET, _answered(_render([CLEARNET, ONION])))

    def test_a_host_without_siblings_overrides_nothing(self) -> None:
        self.assertEqual(_answered(_render([CLEARNET])), [])

    def test_the_request_host_selects_the_site_url_parameter(self) -> None:
        php = _render([CLEARNET, ONION])
        self.assertTrue(php.startswith("<?php\nreturn "))
        self.assertIn("$_SERVER['HTTP_HOST']", php)
        self.assertIn("return ['siteUrl' => $siteUrl];", php)

    def test_the_deploy_writes_the_file_espocrm_reads_as_its_override(self) -> None:
        self.assertIn(
            "'data/config-override.php'",
            load_yaml(ROLE / ROLE_FILE_VARS_MAIN)["ESPOCRM_CONFIG_OVERRIDE_FILE"],
        )
        writers = [
            task
            for task in load_yaml_any(ROLE / "tasks" / "02_manager_ops.yml")
            if "config-override.php.j2" in str(task.get("ansible.builtin.shell", {}))
        ]
        self.assertEqual(len(writers), 1)
        self.assertIn(
            "ESPOCRM_CONFIG_OVERRIDE_FILE", writers[0]["ansible.builtin.shell"]["cmd"]
        )


if __name__ == "__main__":
    unittest.main()
