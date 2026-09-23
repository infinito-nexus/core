"""The router picks a model that can serve the request, or nothing at all.

The hook ships as a template because the alias it answers to has to match the
one the route builder publishes. It is rendered here the way the role renders
it into the container, then exercised as plain Python: a wrong estimate or a
missing filter does not fail the render, it dispatches a prompt to a model that
cannot hold it and fails at the backend, after the choice was already made.

The catalog is passed in rather than taken from the installed litellm, so these
cases state which facts they rely on instead of inheriting 1595 of them.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from utils.cache.files import read_text

from . import PROJECT_ROOT

TEMPLATE = PROJECT_ROOT / "roles/svc-ai-litellm/templates/router_hook.py.j2"
ALIAS = "auto"

CATALOG = {
    "gpt-4o-mini": {
        "max_input_tokens": 128000,
        "max_output_tokens": 16384,
        "supports_vision": True,
        "supports_function_calling": True,
        "input_cost_per_token": 1.5e-07,
    },
    "claude-sonnet-4-5": {
        "max_input_tokens": 200000,
        "supports_vision": True,
        "supports_function_calling": True,
        "input_cost_per_token": 3e-06,
    },
    "ollama/llama3": {"max_input_tokens": 8192, "input_cost_per_token": 0.0},
}


def _stub_litellm():
    """The hook imports litellm at module scope; it is not a test dependency."""
    if "litellm" in sys.modules:
        return
    package = types.ModuleType("litellm")
    integrations = types.ModuleType("litellm.integrations")
    custom_logger = types.ModuleType("litellm.integrations.custom_logger")

    class CustomLogger:
        pass

    custom_logger.CustomLogger = CustomLogger
    package.model_cost = {}
    sys.modules["litellm"] = package
    sys.modules["litellm.integrations"] = integrations
    sys.modules["litellm.integrations.custom_logger"] = custom_logger


def load():
    """The rendered hook, imported as the container would import it."""
    _stub_litellm()
    env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - Python source, not markup
    env.filters["to_json"] = json.dumps
    source = env.from_string(read_text(str(TEMPLATE))).render(
        LITELLM_ROUTER_ALIAS=ALIAS,
    )
    module = types.ModuleType("router_hook_under_test")
    module.__file__ = str(Path(TEMPLATE).with_suffix(""))
    exec(compile(source, str(TEMPLATE), "exec"), module.__dict__)
    return module


def local(alias, *, model=None, context=None, traits=None):
    """A route served by a backend of this deployment, so it costs nothing."""
    return _route(
        alias, {"model": model or alias, "api_base": "http://backend"}, context, traits
    )


def remote(alias, *, model=None, context=None, traits=None):
    """A route served by a keyed provider."""
    params = {"model": model or alias, "api_key": "os.environ/X_API_KEY"}
    return _route(alias, params, context, traits)


def mock(alias, *, context=None, traits=None):
    """A route that answers from its own declared response."""
    params = {"model": f"openai/{alias}", "mock_response": "pong"}
    return _route(alias, params, context, traits)


def _route(alias, params, context, traits):
    entry = {"model_name": alias, "litellm_params": params}
    info = {}
    if context:
        info["max_input_tokens"] = context
    if traits:
        info["traits"] = traits
    if info:
        entry["model_info"] = info
    return entry


class HookCase:
    def setUp(self) -> None:
        self.hook = load()
        self.need = self.hook.summarize({})

    def eligible(self, routes, need=None, catalog=None):
        return self.hook.eligible(
            routes, need or self.need, ALIAS, CATALOG if catalog is None else catalog
        )

    def aliases(self, routes, need=None, catalog=None):
        return [entry["model_name"] for entry in self.eligible(routes, need, catalog)]


class TestSummarize(HookCase, unittest.TestCase):
    def test_plain_text_is_counted_and_rounded_up(self) -> None:
        self.assertEqual(
            self.hook.summarize({"messages": [{"content": "abcd"}]})["input_tokens"], 2
        )

    def test_an_image_part_raises_the_vision_demand(self) -> None:
        need = self.hook.summarize(
            {"messages": [{"content": [{"type": "image_url", "image_url": {}}]}]}
        )
        self.assertTrue(need["vision"])

    def test_text_parts_of_a_multipart_message_are_counted(self) -> None:
        need = self.hook.summarize(
            {"messages": [{"content": [{"type": "text", "text": "abcdef"}]}]}
        )
        self.assertEqual(need["input_tokens"], 2)

    def test_tools_raise_the_tool_demand(self) -> None:
        self.assertTrue(self.hook.summarize({"tools": [{"type": "function"}]})["tools"])

    def test_an_empty_request_demands_nothing(self) -> None:
        self.assertEqual(
            self.hook.summarize({}),
            {"input_tokens": 0, "vision": False, "tools": False, "max_output": 0},
        )


class TestCapabilities(HookCase, unittest.TestCase):
    """What a route can do comes from the catalog unless it says otherwise."""

    def test_a_catalogued_model_needs_no_declaration(self) -> None:
        caps = self.hook.capabilities(
            remote("openai/gpt-4o-mini", model="openai/gpt-4o-mini"), CATALOG
        )
        self.assertEqual(
            (caps["context"], caps["vision"], caps["tools"], caps["cost"]),
            (128000, True, True, 1.5e-07),
            "the catalog ships these facts in the image, so declaring them in "
            "meta/services.yml would only duplicate them and rot",
        )

    def test_a_prefixed_key_is_tried_before_the_bare_one(self) -> None:
        caps = self.hook.capabilities(local("llama3", model="ollama/llama3"), CATALOG)
        self.assertEqual(caps["context"], 8192)

    def test_a_declaration_overrides_the_catalog(self) -> None:
        caps = self.hook.capabilities(
            remote("m", model="openai/gpt-4o-mini", traits={"vision": False}), CATALOG
        )
        self.assertFalse(caps["vision"])
        self.assertEqual(caps["context"], 128000)

    def test_a_declared_window_outranks_the_catalogued_one(self) -> None:
        caps = self.hook.capabilities(
            remote("m", model="openai/gpt-4o-mini", context=4096), CATALOG
        )
        self.assertEqual(caps["context"], 4096)

    def test_an_uncatalogued_local_route_is_free(self) -> None:
        self.assertEqual(
            self.hook.capabilities(local("qwen2.5:0.5b"), CATALOG)["cost"], 0.0
        )

    def test_a_mock_is_free(self) -> None:
        self.assertEqual(self.hook.capabilities(mock("mock/x"), CATALOG)["cost"], 0.0)

    def test_an_uncatalogued_keyed_route_sorts_behind_every_priced_one(self) -> None:
        cost = self.hook.capabilities(remote("openrouter/auto"), CATALOG)["cost"]
        self.assertGreater(cost, CATALOG["claude-sonnet-4-5"]["input_cost_per_token"])

    def test_an_uncatalogued_model_claims_no_capability(self) -> None:
        caps = self.hook.capabilities(local("qwen2.5:0.5b"), CATALOG)
        self.assertEqual(
            (caps["vision"], caps["tools"], caps["context"]), (False, False, None)
        )


class TestEligible(HookCase, unittest.TestCase):
    def test_the_router_never_picks_itself(self) -> None:
        self.assertEqual(self.aliases([local(ALIAS), local("small")]), ["small"])

    def test_a_window_smaller_than_the_prompt_is_dropped(self) -> None:
        need = {**self.need, "input_tokens": 9000}
        self.assertEqual(
            self.aliases(
                [local("small", context=8192), local("big", context=32768)], need
            ),
            ["big"],
        )

    def test_a_catalogued_window_is_enforced_without_a_declaration(self) -> None:
        need = {**self.need, "input_tokens": 9000}
        self.assertEqual(
            self.aliases([local("llama3", model="ollama/llama3")], need), []
        )

    def test_the_requested_output_counts_against_the_window(self) -> None:
        need = {**self.need, "input_tokens": 8000, "max_output": 500}
        self.assertEqual(self.aliases([local("small", context=8192)], need), [])

    def test_an_unknown_window_is_not_enforced(self) -> None:
        need = {**self.need, "input_tokens": 999999}
        self.assertEqual(self.aliases([local("unknown")], need), ["unknown"])

    def test_a_vision_demand_drops_a_model_without_it(self) -> None:
        need = {**self.need, "vision": True}
        routes = [local("text"), remote("seeing", model="openai/gpt-4o-mini")]
        self.assertEqual(self.aliases(routes, need), ["seeing"])

    def test_a_tool_demand_drops_a_model_without_it(self) -> None:
        need = {**self.need, "tools": True}
        routes = [local("plain"), local("calling", traits={"tools": True})]
        self.assertEqual(self.aliases(routes, need), ["calling"])

    def test_a_declared_output_cap_below_the_request_is_dropped(self) -> None:
        need = {**self.need, "max_output": 4096}
        self.assertEqual(
            self.aliases([local("short", traits={"max_output": 512})], need), []
        )


class TestLoudFailure(HookCase, unittest.TestCase):
    """A router that cannot route says so; it never answers from a default.

    The proxy turns a string returned by the hook into a RejectedRequestError
    carrying that text, so the caller gets the reason rather than a reply from
    whichever model happened to be first.
    """

    def reject(self, routes, need=None):
        import asyncio

        data = {"model": ALIAS, "messages": [{"content": "x"}]}
        if need:
            data.update(need)
        router = types.SimpleNamespace(model_list=routes)
        proxy = types.ModuleType("litellm.proxy.proxy_server")
        proxy.llm_router = router
        sys.modules["litellm.proxy"] = types.ModuleType("litellm.proxy")
        sys.modules["litellm.proxy.proxy_server"] = proxy
        return asyncio.run(
            self.hook.instance.async_pre_call_hook(None, None, data, "completion")
        )

    def test_a_request_for_another_model_is_not_touched(self) -> None:
        import asyncio

        data = {"model": "something-else"}
        self.assertIsNone(
            asyncio.run(
                self.hook.instance.async_pre_call_hook(None, None, data, "completion")
            )
        )

    def test_no_eligible_model_is_rejected_with_the_demand(self) -> None:
        verdict = self.reject([local("tiny", context=1)], {"max_tokens": 9999})
        self.assertIsInstance(verdict, str)
        self.assertIn("cannot route", verdict)

    def test_a_routable_request_is_rewritten(self) -> None:
        data = self.reject([local("big", context=99999)])
        self.assertEqual(data["model"], "big")


class TestDecider(HookCase, unittest.TestCase):
    def test_the_cheapest_price_wins(self) -> None:
        routes = [
            remote("pricey", model="anthropic/claude-sonnet-4-5"),
            remote("cheap", model="openai/gpt-4o-mini"),
        ]
        self.assertEqual(self.hook.decide(self.eligible(routes)), "cheap")

    def test_a_local_model_beats_every_paid_one(self) -> None:
        routes = [remote("paid", model="openai/gpt-4o-mini"), local("home")]
        self.assertEqual(self.hook.decide(self.eligible(routes)), "home")

    def test_a_tie_is_broken_by_alias_so_a_rerun_repeats(self) -> None:
        routes = [local("b"), local("a")]
        first = self.hook.decide(self.eligible(routes))
        second = self.hook.decide(self.eligible(list(reversed(routes))))
        self.assertEqual((first, second), ("a", "a"))


if __name__ == "__main__":
    unittest.main()
