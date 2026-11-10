"""WordPress receives one comma list of network siblings per site, sites split by semicolons."""

from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.filter.network_of import FilterModule as NetworkFilters
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_VARS = PROJECT_ROOT / "roles" / "web-app-wordpress" / ROLE_FILE_VARS_MAIN
ONION = "a" * 56 + ".onion"


def _onion(clearnet: str) -> str:
    return clearnet.removesuffix("main.test") + ONION


def _render(domains: list[str]) -> tuple[list[str], str, list[str]]:
    """
    Args:
        domains: the answer of lookup('domains', 'web-app-wordpress') on the host.

    Returns:
        WORDPRESS_SITE_DOMAINS, WORDPRESS_NETWORK_BASE_URLS and WORDPRESS_SITE_URLS as vars/main.yml resolves them.
    """
    served = set(domains)

    def lookup(*terms: str):
        if terms[0] == "tls" and terms[2] == "url.base":
            return f"https://{terms[1]}/"
        if terms[0] == "network_urls":
            clearnet = terms[1].removeprefix("https://").rstrip("/")
            onion = _onion(clearnet)
            return [terms[1]] + ([f"http://{onion}/"] if onion in served else [])
        raise AssertionError(f"the base URLs render an unexpected lookup{terms}")

    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.filters.update(NetworkFilters().filters())
    env.filters["split"] = lambda value, separator: value.split(separator)
    variables = load_yaml(str(ROLE_VARS))

    def expression(name: str):
        return env.compile_expression(
            variables[name].strip().removeprefix("{{").removesuffix("}}")
        )

    site_domains = expression("WORDPRESS_SITE_DOMAINS")(WORDPRESS_DOMAINS=domains)
    base_urls = env.from_string(variables["WORDPRESS_NETWORK_BASE_URLS"]).render(
        WORDPRESS_SITE_DOMAINS=site_domains, lookup=lookup
    )
    site_urls = expression("WORDPRESS_SITE_URLS")(WORDPRESS_NETWORK_BASE_URLS=base_urls)
    return site_domains, base_urls, site_urls


THREE_SITES = ["blog.main.test", "biberblog.main.test", "biber.blog.main.test"]


class TestNetworkBaseUrls(unittest.TestCase):
    def test_a_single_site_lists_its_siblings_in_one_group(self):
        _, base_urls, _ = _render(["blog.main.test", _onion("blog.main.test")])
        self.assertEqual(f"https://blog.main.test/,http://blog.{ONION}/", base_urls)

    def test_every_site_of_a_network_gets_its_own_group(self):
        _, base_urls, _ = _render(THREE_SITES + [_onion(d) for d in THREE_SITES])
        self.assertEqual(
            f"https://blog.main.test/,http://blog.{ONION}/;"
            f"https://biberblog.main.test/,http://biberblog.{ONION}/;"
            f"https://biber.blog.main.test/,http://biber.blog.{ONION}/",
            base_urls,
        )

    def test_every_site_is_created_on_its_canonical_url(self):
        _, _, site_urls = _render(THREE_SITES + [_onion(d) for d in THREE_SITES])
        self.assertEqual([f"https://{d}/" for d in THREE_SITES], site_urls)

    def test_a_network_sibling_is_no_site_of_its_own(self):
        site_domains, _, site_urls = _render(
            THREE_SITES + [_onion(d) for d in THREE_SITES]
        )
        self.assertEqual(THREE_SITES, site_domains)
        self.assertFalse([url for url in site_urls if ".onion" in url])

    def test_a_clearnet_only_host_lists_the_canonical_url_alone(self):
        site_domains, base_urls, site_urls = _render(["blog.main.test"])
        self.assertEqual(["blog.main.test"], site_domains)
        self.assertEqual("https://blog.main.test/", base_urls)
        self.assertEqual(["https://blog.main.test/"], site_urls)


if __name__ == "__main__":
    unittest.main()
