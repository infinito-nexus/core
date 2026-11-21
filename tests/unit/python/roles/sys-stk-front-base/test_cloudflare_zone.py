from __future__ import annotations

import unittest

import jinja2

from plugins.filter.network_of import FilterModule
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.networks.reachability import (
    CLEARNET,
    TOR,
    network,
    network_of,
    sibling_domain,
)
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

MAIN = PROJECT_ROOT / "roles/sys-stk-front-base" / ROLE_FILE_TASKS_MAIN
CLOUDFLARE_TASKS = "01_cloudflare.yml"
PRIMARY = "example.org"
NODE = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw" + network(TOR).suffix
CLEARNET_DOMAIN = f"mastodon.{PRIMARY}"
ONION_DOMAIN = sibling_domain(CLEARNET_DOMAIN, TOR, PRIMARY, NODE)


def _cloudflare_conditions() -> list[str]:
    include = next(
        task
        for task in load_yaml_str(read_text(str(MAIN)))
        if (task.get("include_tasks") or task.get("ansible.builtin.include_tasks"))
        == CLOUDFLARE_TASKS
    )
    when = include.get("when", [])
    return [when] if isinstance(when, str) else list(when)


def _asks_for_a_zone(dns_provider: str, domain: str) -> bool:
    environment = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    environment.filters.update(FilterModule().filters())
    return all(
        bool(
            environment.compile_expression(condition)(
                DNS_PROVIDER=dns_provider, domain=domain
            )
        )
        for condition in _cloudflare_conditions()
    )


class TestCloudflareZone(unittest.TestCase):
    def test_the_fixture_serves_one_vhost_in_both_networks(self) -> None:
        self.assertEqual(network_of(CLEARNET_DOMAIN), CLEARNET)
        self.assertEqual(network_of(ONION_DOMAIN), TOR)

    def test_a_tor_only_node_asks_cloudflare_for_no_onion_zone(self) -> None:
        self.assertFalse(
            _asks_for_a_zone("cloudflare", ONION_DOMAIN),
            "an onion name has no Cloudflare zone: the lookup aborts the deploy "
            "and hands the node's onion address to the Cloudflare API",
        )

    def test_a_clearnet_domain_still_asks_cloudflare_for_its_zone(self) -> None:
        self.assertTrue(_asks_for_a_zone("cloudflare", CLEARNET_DOMAIN))

    def test_another_dns_provider_asks_cloudflare_for_no_zone(self) -> None:
        for domain in (CLEARNET_DOMAIN, ONION_DOMAIN):
            with self.subTest(domain=domain):
                self.assertFalse(_asks_for_a_zone("localhost", domain))


if __name__ == "__main__":
    unittest.main()
