from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-suitecrm"
APPLICATION_ID = "web-app-suitecrm"
CLEARNET = "https://suite.crm.example.test"
ONION = "http://suite.crm." + "a" * 56 + ".onion"


def _variables() -> dict:
    return load_yaml(ROLE / ROLE_FILE_VARS_MAIN)


def _sibling_site_urls(network_urls: list[str]) -> list[str]:
    """
    Args:
        network_urls: the answer of lookup('network_urls', <canonical origin>) on the host.

    Returns:
        SUITECRM_SIBLING_SITE_URLS as vars/main.yml resolves it.
    """

    def lookup(*terms: str):
        if terms == ("tls", APPLICATION_ID, "url.origin"):
            return CLEARNET
        if terms == ("network_urls", CLEARNET):
            return network_urls
        raise AssertionError(f"the sibling URLs render an unexpected lookup{terms}")

    expression = _variables()["SUITECRM_SIBLING_SITE_URLS"]
    return Environment(
        undefined=StrictUndefined, autoescape=select_autoescape()
    ).compile_expression(expression.strip().removeprefix("{{").removesuffix("}}"))(
        lookup=lookup, application_id=APPLICATION_ID
    )


def _render(network_urls: list[str]) -> str:
    """
    Args:
        network_urls: the answer of lookup('network_urls', <canonical origin>) on the host.

    Returns:
        The PHP file the container runs as auto_prepend_file.
    """
    env = Environment(
        loader=FileSystemLoader(str(ROLE / "templates")),
        undefined=StrictUndefined,
        trim_blocks=True,
        keep_trailing_newline=True,
        autoescape=select_autoescape(),
    )
    return env.get_template("site_url.php.j2").render(
        SUITECRM_SIBLING_SITE_URLS=_sibling_site_urls(network_urls)
    )


def _answered(php: str) -> list[str]:
    return re.findall(r"^    '([^']+)',$", php, re.MULTILINE)


class TestSiteUrlPrepend(unittest.TestCase):
    def test_the_onion_sibling_is_answered_with_its_plaintext_origin(self) -> None:
        self.assertEqual(
            _answered(_render([CLEARNET, ONION])),
            [ONION],
            "SuiteCRM names SITE_URL/saml/acs as the assertion consumer, so an onion "
            "login lands its session on the clearnet host unless SITE_URL is the onion origin",
        )

    def test_the_canonical_host_keeps_the_configured_site_url(self) -> None:
        self.assertNotIn(CLEARNET, _answered(_render([CLEARNET, ONION])))

    def test_a_host_without_siblings_sets_nothing(self) -> None:
        self.assertEqual(_answered(_render([CLEARNET])), [])

    def test_the_request_host_selects_the_site_url_the_kernel_keeps(self) -> None:
        php = _render([CLEARNET, ONION])
        self.assertTrue(php.startswith("<?php\n(static function"))
        self.assertIn("$_SERVER['HTTP_HOST']", php)
        self.assertIn("$_ENV['SITE_URL'] = $siteUrl;", php)

    def test_php_prepends_the_mounted_script(self) -> None:
        variables = _variables()
        mounts = load_yaml(ROLE / ROLE_FILE_META_VOLUMES)["site_url_script"]
        self.assertEqual(
            [mount["service"] for mount in mounts["mounts"]],
            ["suitecrm"],
        )
        self.assertEqual(
            variables["SUITECRM_SITE_URL_SCRIPT_DOCKER"],
            "{{ lookup('volume', application_id, 'site_url_script').target }}",
        )
        self.assertIn("'site_url.php'", mounts["source"])
        self.assertIn(
            "auto_prepend_file = {{ SUITECRM_SITE_URL_SCRIPT_DOCKER }}",
            read_text(str(ROLE / "templates" / "php.ini.j2")),
        )
        renders = [
            task["stack_host_template"]
            for task in load_yaml_any(ROLE / "tasks" / "01_manager_ops.yml")
            if task.get("stack_host_template", {}).get("src") == "site_url.php.j2"
        ]
        self.assertEqual(
            renders,
            [{"src": "site_url.php.j2", "dest": "{{ SUITECRM_SITE_URL_SCRIPT_HOST }}"}],
        )
        self.assertIn("'site_url.php'", variables["SUITECRM_SITE_URL_SCRIPT_HOST"])


if __name__ == "__main__":
    unittest.main()
