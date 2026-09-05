"""How Stalwart routes .onion recipients to the Tor SMTP gateway.

Stalwart has no outbound SOCKS of its own, so ``14_onion_route.yml`` provisions
a relay ``MtaRoute`` to the gateway and points the ``MtaOutboundStrategy`` route
expression at it for ``.onion`` recipients. The one property that must never
regress: the strategy still sends local recipients to ``local`` and everything
else to ``mx`` — adding the onion branch must not break normal delivery.
"""

from __future__ import annotations

import json
import unittest

from jinja2 import Environment, StrictUndefined

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-stalwart"
TASK = ROLE / "tasks" / "14_onion_route.yml"
ROUTE_CREATE = ROLE / "templates" / "jmap" / "route" / "create.json.j2"
STRATEGY_GET = ROLE / "templates" / "jmap" / "strategy" / "get.json.j2"
STRATEGY_CREATE = ROLE / "templates" / "jmap" / "strategy" / "create.json.j2"
STRATEGY_UPDATE = ROLE / "templates" / "jmap" / "strategy" / "update.json.j2"

ROUTE_NAME = "onion"


def _render(template_path, **variables) -> str:
    env = Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - JMAP request bodies, never HTML
    )
    env.filters["to_json"] = json.dumps
    env.filters["int"] = int
    return env.from_string(read_text(template_path)).render(**variables)


def _route_expr_from_task() -> dict:
    tasks = load_yaml_any(str(TASK), default_if_missing=[])
    for task in tasks:
        facts = task.get("set_fact") or task.get("ansible.builtin.set_fact") or {}
        if "stalwart_route_expr" in facts:
            return facts["stalwart_route_expr"]
    raise AssertionError("stalwart_route_expr set_fact not found in 14_onion_route.yml")


class TestOutboundStrategyExpression(unittest.TestCase):
    def setUp(self):
        self.expr = _route_expr_from_task()

    def test_local_recipients_still_route_to_local(self):
        first = self.expr["match"]["0"]
        self.assertEqual(first["if"], "is_local_domain(rcpt_domain)")
        self.assertEqual(first["then"], "'local'")

    def test_local_is_evaluated_before_onion(self):
        """A local .onion address must be delivered locally, not relayed out."""
        keys = list(self.expr["match"].keys())
        self.assertEqual(keys, ["0", "1"])
        self.assertIn("is_local_domain", self.expr["match"]["0"]["if"])
        self.assertIn("ends_with", self.expr["match"]["1"]["if"])

    def test_onion_recipients_route_to_the_onion_route(self):
        """then is a Stalwart expression string literal naming the route, from
        the same SPOT var the relay route registers itself under."""
        onion = self.expr["match"]["1"]
        self.assertEqual(onion["if"], "ends_with(rcpt_domain, '.onion')")
        self.assertEqual(onion["then"], "'{{ STALWART_ONION_ROUTE_NAME }}'")

    def test_everything_else_falls_back_to_mx(self):
        self.assertEqual(self.expr["else"], "'mx'")


class TestStrategyTemplateRendersValidJson(unittest.TestCase):
    def test_the_singleton_route_is_set_from_the_expression(self):
        expr = _route_expr_from_task()
        rendered = _render(STRATEGY_UPDATE, stalwart_route_expr=expr)
        body = json.loads(rendered)
        method, args, _tag = body["methodCalls"][0]
        self.assertEqual(method, "x:MtaOutboundStrategy/set")
        self.assertEqual(args["update"]["singleton"]["route"], expr)

    def test_create_seeds_a_new_singleton_with_the_route(self):
        expr = _route_expr_from_task()
        rendered = _render(STRATEGY_CREATE, stalwart_route_expr=expr)
        body = json.loads(rendered)
        method, args, _tag = body["methodCalls"][0]
        self.assertEqual(method, "x:MtaOutboundStrategy/set")
        (created,) = args["create"].values()
        self.assertEqual(created["route"], expr)

    def test_get_queries_the_singleton_by_id(self):
        """The singleton is NOT enumerated by get(ids:null); it must be queried
        by its fixed "singleton" id or existence detection is always wrong."""
        body = json.loads(_render(STRATEGY_GET))
        method, args, _tag = body["methodCalls"][0]
        self.assertEqual(method, "x:MtaOutboundStrategy/get")
        self.assertEqual(args["ids"], ["singleton"])


class TestRelayRouteRendersValidJson(unittest.TestCase):
    def _create(self):
        rendered = _render(
            ROUTE_CREATE,
            STALWART_ONION_ROUTE_NAME=ROUTE_NAME,
            STALWART_ONION_RELAY_HOST="tor-smtp",
            STALWART_ONION_RELAY_PORT=1525,
        )
        body = json.loads(rendered)
        return body["methodCalls"][0]

    def test_it_creates_a_relay_route_to_the_gateway(self):
        method, args, _tag = self._create()
        self.assertEqual(method, "x:MtaRoute/set")
        route = args["create"][ROUTE_NAME]
        self.assertEqual(route["@type"], "Relay")
        self.assertEqual(route["name"], ROUTE_NAME)
        self.assertEqual(route["address"], "tor-smtp")
        self.assertEqual(route["port"], 1525)

    def test_the_relay_hop_is_plaintext_smtp(self):
        """The gateway speaks plaintext SMTP on an internal network; there is no
        cert to validate on a .onion relay hop."""
        _method, args, _tag = self._create()
        route = args["create"][ROUTE_NAME]
        self.assertEqual(route["protocol"], "smtp")
        self.assertFalse(route["implicitTls"])


if __name__ == "__main__":
    unittest.main()
