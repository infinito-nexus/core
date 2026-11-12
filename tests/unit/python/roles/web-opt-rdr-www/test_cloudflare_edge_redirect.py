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

EDGE_TASKS = (
    PROJECT_ROOT / "roles/web-opt-rdr-www/tasks/_01_cloudflare_edge_redirect.yml"
)
RULE_TASKS = "_02_cloudflare_redirect_rule.yml"
PRIMARY = "example.org"
NODE = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw" + network(TOR).suffix
HOMEPAGE = "homepage.example.net"
CLEARNET_SOURCE = f"www.{PRIMARY}"
ONION_SOURCE = sibling_domain(f"w3redirect.{PRIMARY}", TOR, PRIMARY, NODE)


def _rule_conditions() -> list[str]:
    include = next(
        task
        for task in load_yaml_str(read_text(str(EDGE_TASKS)))
        if (task.get("include_tasks") or task.get("ansible.builtin.include_tasks"))
        == RULE_TASKS
    )
    when = include.get("when", [])
    return [when] if isinstance(when, str) else list(when)


def _reaches_cloudflare(source: str, target: str) -> bool:
    environment = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    environment.filters.update(FilterModule().filters())
    redirect = {"source": source, "target": target}
    return all(
        bool(environment.compile_expression(condition)(www_redirect=redirect))
        for condition in _rule_conditions()
    )


class TestCloudflareEdgeRedirect(unittest.TestCase):
    def test_the_fixture_spans_both_networks(self) -> None:
        self.assertEqual(network_of(CLEARNET_SOURCE), CLEARNET)
        self.assertEqual(network_of(ONION_SOURCE), TOR)

    def test_a_clearnet_mapping_still_becomes_a_cloudflare_rule(self) -> None:
        self.assertTrue(_reaches_cloudflare(CLEARNET_SOURCE, PRIMARY))

    def test_a_tor_only_node_sends_no_onion_source_to_cloudflare(self) -> None:
        self.assertFalse(
            _reaches_cloudflare(ONION_SOURCE, HOMEPAGE),
            "an onion name has no Cloudflare zone: the zone lookup aborts the "
            "deploy and hands the node's onion address to the Cloudflare API",
        )

    def test_an_onion_target_is_never_published_as_a_cloudflare_cname(self) -> None:
        self.assertFalse(
            _reaches_cloudflare(CLEARNET_SOURCE, ONION_SOURCE),
            "the rule writes the target as a public CNAME value",
        )


if __name__ == "__main__":
    unittest.main()
