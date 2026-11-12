from __future__ import annotations

import unittest

import jinja2
from jinja2.nativetypes import NativeEnvironment

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
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-opt-rdr-www"
VARS = ROLE / ROLE_FILE_VARS_MAIN
TASKS = ROLE / ROLE_FILE_TASKS_MAIN
EDGE_TASKS = ROLE / "tasks/_01_cloudflare_edge_redirect.yml"
EDGE_INCLUDE = "_01_cloudflare_edge_redirect.yml"
RULE_TASKS = "_02_cloudflare_redirect_rule.yml"
ORIGIN_ROLE = "web-opt-rdr-domains"
PRIMARY = "example.org"
NODE = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw" + network(TOR).suffix
HOMEPAGE = "homepage.example.net"
ROLE_DOMAIN = f"w3redirect.{PRIMARY}"
CLEARNET_MAPPING = {"source": f"www.{PRIMARY}", "target": PRIMARY}
ONION_SOURCE_MAPPING = {
    "source": sibling_domain(ROLE_DOMAIN, TOR, PRIMARY, NODE),
    "target": HOMEPAGE,
}
ONION_TARGET_MAPPING = {
    "source": ROLE_DOMAIN,
    "target": sibling_domain(f"home.{PRIMARY}", TOR, PRIMARY, NODE),
}
MAPPINGS = [CLEARNET_MAPPING, ONION_SOURCE_MAPPING, ONION_TARGET_MAPPING]


def _environment() -> NativeEnvironment:
    environment = NativeEnvironment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    environment.filters.update(FilterModule().filters())
    return environment


def _render(value, context: dict):
    if not isinstance(value, str) or "{{" not in value:
        return value
    return _environment().from_string(value).render(context)


def _holds(when, context: dict) -> bool:
    conditions = [] if when is None else [when] if isinstance(when, str) else when
    return all(
        bool(_environment().compile_expression(condition)(**context))
        for condition in conditions
    )


def _context(flavor: str) -> dict:
    context = {
        "DNS_PROVIDER": "cloudflare",
        "REDIRECT_WWW_FLAVOR": flavor,
        "REDIRECT_WWW_DOMAINS": MAPPINGS,
    }
    for name, value in load_yaml_str(read_text(str(VARS))).items():
        if name.startswith("REDIRECT_WWW_") and name not in context:
            context[name] = _render(value, context)
    return context


def _task(path, include: str) -> dict:
    return next(
        task
        for task in load_yaml_str(read_text(str(path)))
        if include
        in (
            task.get("include_tasks"),
            task.get("ansible.builtin.include_tasks"),
            (task.get("vars") or {}).get("load_app_id"),
        )
    )


def _origin_redirects(flavor: str) -> list[dict]:
    context = _context(flavor)
    include = _task(TASKS, ORIGIN_ROLE)
    if not _holds(include.get("when"), context):
        return []
    return _render(include["vars"]["web_opt_rdr_domains_mappings"], context)


def _cloudflare_rules(flavor: str) -> list[dict]:
    context = _context(flavor)
    if not _holds(_task(TASKS, EDGE_INCLUDE).get("when"), context):
        return []
    include = _task(EDGE_TASKS, RULE_TASKS)
    return [
        redirect
        for redirect in _render(include["loop"], context)
        if _holds(include.get("when"), {**context, "www_redirect": redirect})
    ]


class TestCloudflareEdgeRedirect(unittest.TestCase):
    def test_the_fixture_spans_both_networks(self) -> None:
        self.assertEqual(network_of(CLEARNET_MAPPING["source"]), CLEARNET)
        self.assertEqual(network_of(ONION_SOURCE_MAPPING["source"]), TOR)
        self.assertEqual(network_of(ONION_TARGET_MAPPING["target"]), TOR)

    def test_a_clearnet_mapping_stays_on_the_edge(self) -> None:
        self.assertEqual(_cloudflare_rules("edge"), [CLEARNET_MAPPING])
        self.assertNotIn(CLEARNET_MAPPING, _origin_redirects("edge"))

    def test_an_onion_source_gets_its_redirect_from_the_origin(self) -> None:
        self.assertIn(
            ONION_SOURCE_MAPPING,
            _origin_redirects("edge"),
            "Cloudflare has no zone for an onion name, so only the origin can "
            "serve its redirect",
        )
        self.assertNotIn(ONION_SOURCE_MAPPING, _cloudflare_rules("edge"))

    def test_an_onion_target_is_never_published_as_a_cloudflare_cname(self) -> None:
        self.assertNotIn(
            ONION_TARGET_MAPPING,
            _cloudflare_rules("edge"),
            "the rule writes the target as a public CNAME value",
        )
        self.assertIn(ONION_TARGET_MAPPING, _origin_redirects("edge"))

    def test_the_origin_flavor_serves_every_mapping_from_the_origin(self) -> None:
        self.assertEqual(_cloudflare_rules("origin"), [])
        self.assertEqual(_origin_redirects("origin"), MAPPINGS)


if __name__ == "__main__":
    unittest.main()
