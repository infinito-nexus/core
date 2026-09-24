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
import unittest.mock
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

TEMPLATE = PROJECT_ROOT / "roles/svc-ai-litellm/templates/router_hook.py.j2"
ALIAS = "auto"
TODAY = "2026-09-24"
JEFF_URL = "http://jeff:8000"

SHIPPED = load_yaml(PROJECT_ROOT / "roles/svc-ai-litellm" / ROLE_FILE_META_SERVICES)[
    "litellm"
]
SHIPPED_WEIGHTS = SHIPPED["router_weights"]
SHIPPED_MIN_CHARS_PER_TOKEN = SHIPPED["router_min_chars_per_token"]
SHIPPED_STATE_CHARS = SHIPPED["router_state_chars"]

CATALOG = {
    "gpt-4o-mini": {
        "mode": "chat",
        "max_input_tokens": 128000,
        "max_output_tokens": 16384,
        "supports_vision": True,
        "supports_function_calling": True,
        "supports_tool_choice": True,
        "supports_response_schema": True,
        "supports_pdf_input": True,
        "supports_prompt_caching": True,
        "input_cost_per_token": 1.5e-07,
        "output_cost_per_token": 6e-07,
        "tpm": 4000000,
    },
    "claude-sonnet-4-5": {
        "mode": "chat",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "supports_function_calling": True,
        "input_cost_per_token": 3e-06,
        "output_cost_per_token": 1.5e-05,
    },
    "ollama/llama3": {
        "mode": "chat",
        "max_input_tokens": 8192,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
    },
    "text-embedding-3-small": {"mode": "embedding", "max_input_tokens": 8191},
    "no-system": {"mode": "chat", "supports_system_messages": False},
    "retired": {"mode": "chat", "deprecation_date": "2025-01-01"},
    "outlives-us": {"mode": "chat", "deprecation_date": "2099-01-01"},
    "prose-dated": {"mode": "chat", "deprecation_date": "date when the model dies"},
    "one-image": {"mode": "chat", "supports_vision": True, "max_images_per_prompt": 1},
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


def load(*, remote_fallback=False, weights=None, strategy="weighted"):
    """The rendered hook, imported as the container would import it."""
    _stub_litellm()
    env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - Python source, not markup
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = bool
    source = env.from_string(read_text(str(TEMPLATE))).render(
        LITELLM_ROUTER_ALIAS=ALIAS,
        LITELLM_ROUTER_REMOTE_FALLBACK=remote_fallback,
        LITELLM_ROUTER_WEIGHTS=SHIPPED_WEIGHTS if weights is None else weights,
        LITELLM_ROUTER_STRATEGY=strategy,
        LITELLM_ROUTER_MIN_CHARS_PER_TOKEN=SHIPPED_MIN_CHARS_PER_TOKEN,
        LITELLM_ROUTER_STATE_CHARS=SHIPPED_STATE_CHARS,
        LITELLM_JEFF_URL=JEFF_URL,
        LITELLM_JEFF_KEY="jeff-test-key",
        LITELLM_JEFF_MODEL="jev-latest",
        LITELLM_JEFF_TIMEOUT=20,
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
            routes,
            need or self.need,
            ALIAS,
            CATALOG if catalog is None else catalog,
            TODAY,
        )

    def aliases(self, routes, need=None, catalog=None):
        return [entry["model_name"] for entry in self.eligible(routes, need, catalog)]

    def decide(self, routes, need=None, **kwargs):
        need = need or self.need
        return self.hook.decide(self.eligible(routes, need), need, **kwargs)


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
        self.assertEqual(need["images"], 1)

    def test_an_audio_part_raises_the_audio_demand(self) -> None:
        need = self.hook.summarize(
            {"messages": [{"content": [{"type": "input_audio", "input_audio": {}}]}]}
        )
        self.assertTrue(need["audio"])

    def test_a_file_part_raises_the_document_demand(self) -> None:
        need = self.hook.summarize(
            {"messages": [{"content": [{"type": "file", "file": {}}]}]}
        )
        self.assertTrue(need["documents"])

    def test_a_system_role_raises_the_system_demand(self) -> None:
        need = self.hook.summarize(
            {"messages": [{"role": "system", "content": "be brief"}]}
        )
        self.assertTrue(need["system"])

    def test_a_developer_role_counts_as_a_system_message(self) -> None:
        need = self.hook.summarize(
            {"messages": [{"role": "developer", "content": "x"}]}
        )
        self.assertTrue(need["system"])

    def test_a_response_format_raises_the_schema_demand(self) -> None:
        need = self.hook.summarize({"response_format": {"type": "json_schema"}})
        self.assertTrue(need["schema"])

    def test_plain_text_response_format_demands_no_schema(self) -> None:
        self.assertFalse(
            self.hook.summarize({"response_format": {"type": "text"}})["schema"]
        )

    def test_tools_raise_the_tool_demand(self) -> None:
        self.assertTrue(self.hook.summarize({"tools": [{"type": "function"}]})["tools"])

    def test_parallel_tool_calls_raise_their_own_demand(self) -> None:
        self.assertTrue(
            self.hook.summarize({"parallel_tool_calls": True})["parallel_tools"]
        )

    def test_an_empty_request_demands_nothing(self) -> None:
        need = self.hook.summarize({})
        self.assertEqual(need["input_tokens"], 0)
        self.assertFalse(
            any(
                need[key]
                for key in ("vision", "audio", "documents", "system", "tools", "schema")
            )
        )


class TestCapabilities(HookCase, unittest.TestCase):
    """What a route can do comes from the catalog unless it says otherwise."""

    def caps(self, entry):
        return self.hook.capabilities(entry, CATALOG, TODAY)

    def test_a_catalogued_model_needs_no_declaration(self) -> None:
        caps = self.caps(remote("m", model="openai/gpt-4o-mini"))
        self.assertEqual(
            (caps["context"], caps["vision"], caps["tools"], caps["input_cost"]),
            (128000, True, True, 1.5e-07),
            "the catalog ships these facts in the image, so declaring them in "
            "meta/services.yml would only duplicate them and rot",
        )

    def test_the_output_price_is_read_too(self) -> None:
        self.assertEqual(
            self.caps(remote("m", model="openai/gpt-4o-mini"))["output_cost"], 6e-07
        )

    def test_a_prefixed_key_is_tried_before_the_bare_one(self) -> None:
        self.assertEqual(
            self.caps(local("llama3", model="ollama/llama3"))["context"], 8192
        )

    def test_a_declaration_overrides_the_catalog(self) -> None:
        caps = self.caps(
            remote("m", model="openai/gpt-4o-mini", traits={"vision": False})
        )
        self.assertFalse(caps["vision"])
        self.assertEqual(caps["context"], 128000)

    def test_an_uncatalogued_local_route_is_free(self) -> None:
        caps = self.caps(local("qwen2.5:0.5b"))
        self.assertEqual((caps["input_cost"], caps["output_cost"]), (0.0, 0.0))

    def test_an_uncatalogued_keyed_route_sorts_behind_every_priced_one(self) -> None:
        self.assertGreater(self.caps(remote("openrouter/auto"))["input_cost"], 1e-05)

    def test_an_uncatalogued_route_is_still_servable(self) -> None:
        self.assertTrue(
            self.caps(local("qwen2.5:0.5b"))["servable"],
            "a local tag is in no catalog, so reading silence as a non-chat mode "
            "would drop every locally served model",
        )

    def test_an_embedding_model_is_not_servable(self) -> None:
        self.assertFalse(
            self.caps(remote("e", model="text-embedding-3-small"))["servable"]
        )

    def test_system_messages_are_assumed_unless_denied(self) -> None:
        self.assertTrue(self.caps(remote("m", model="claude-sonnet-4-5"))["system"])
        self.assertFalse(self.caps(remote("m", model="no-system"))["system"])

    def test_a_past_deprecation_date_marks_the_route(self) -> None:
        self.assertTrue(self.caps(remote("m", model="retired"))["deprecated"])

    def test_a_future_deprecation_date_does_not(self) -> None:
        self.assertFalse(self.caps(remote("m", model="outlives-us"))["deprecated"])

    def test_a_prose_deprecation_value_is_not_a_date(self) -> None:
        self.assertFalse(
            self.caps(remote("m", model="prose-dated"))["deprecated"],
            "the catalog ships a sample_spec stub whose date field is prose, so "
            "parsing it as a date would retire a model on documentation",
        )


class TestEligible(HookCase, unittest.TestCase):
    def test_the_router_never_picks_itself(self) -> None:
        self.assertEqual(self.aliases([local(ALIAS), local("real")]), ["real"])

    def test_a_window_smaller_than_the_prompt_is_dropped(self) -> None:
        need = {**self.need, "input_tokens": 9000}
        self.assertEqual(
            self.aliases([local("s", context=4096), local("l", context=65536)], need),
            ["l"],
        )

    def test_a_catalogued_window_is_enforced_without_a_declaration(self) -> None:
        need = {**self.need, "input_tokens": 9000}
        self.assertEqual(
            self.aliases([local("llama3", model="ollama/llama3")], need), []
        )

    def test_the_requested_output_counts_against_the_window(self) -> None:
        need = {**self.need, "input_tokens": 4000, "max_output": 500}
        self.assertEqual(self.aliases([local("s", context=4096)], need), [])

    def test_a_vision_demand_drops_a_model_without_it(self) -> None:
        need = {**self.need, "vision": True}
        self.assertEqual(
            self.aliases(
                [local("plain"), remote("v", model="openai/gpt-4o-mini")], need
            ),
            ["v"],
        )

    def test_an_audio_demand_drops_every_model_without_it(self) -> None:
        need = {**self.need, "audio": True}
        self.assertEqual(
            self.aliases([remote("v", model="openai/gpt-4o-mini")], need), []
        )

    def test_a_document_demand_needs_pdf_support(self) -> None:
        need = {**self.need, "documents": True}
        self.assertEqual(
            self.aliases(
                [
                    remote("c", model="claude-sonnet-4-5"),
                    remote("o", model="openai/gpt-4o-mini"),
                ],
                need,
            ),
            ["o"],
        )

    def test_a_schema_demand_needs_response_schema_support(self) -> None:
        need = {**self.need, "schema": True}
        self.assertEqual(
            self.aliases(
                [
                    remote("c", model="claude-sonnet-4-5"),
                    remote("o", model="openai/gpt-4o-mini"),
                ],
                need,
            ),
            ["o"],
        )

    def test_more_images_than_the_route_takes_is_dropped(self) -> None:
        need = {**self.need, "vision": True, "images": 3}
        self.assertEqual(self.aliases([remote("one", model="one-image")], need), [])

    def test_a_system_message_drops_a_route_that_denies_them(self) -> None:
        need = {**self.need, "system": True}
        self.assertEqual(self.aliases([remote("n", model="no-system")], need), [])

    def test_an_embedding_route_is_dropped_even_when_it_would_fit(self) -> None:
        self.assertEqual(
            self.aliases([remote("e", model="text-embedding-3-small")]),
            [],
            "an embedding model answers no chat request, and reaching it fails "
            "at the backend after the choice was made",
        )

    def test_a_deprecated_route_is_dropped(self) -> None:
        self.assertEqual(
            self.aliases([remote("r", model="retired"), local("ok")]), ["ok"]
        )


class TestExpectedCost(HookCase, unittest.TestCase):
    """Ranking on the input price alone reads the cheaper half of the bill."""

    def test_the_output_price_enters_the_estimate(self) -> None:
        need = {**self.need, "input_tokens": 100, "max_output": 1000}
        caps = self.hook.capabilities(
            remote("m", model="openai/gpt-4o-mini"), CATALOG, TODAY
        )
        self.assertAlmostEqual(
            self.hook.expected_cost(caps, need), 100 * 1.5e-07 + 1000 * 6e-07
        )

    def test_a_request_without_max_tokens_still_prices_an_answer(self) -> None:
        caps = self.hook.capabilities(
            remote("m", model="openai/gpt-4o-mini"), CATALOG, TODAY
        )
        self.assertGreater(self.hook.expected_cost(caps, self.need), 0.0)

    def test_a_long_answer_can_invert_the_input_price_order(self) -> None:
        catalog = {
            "wordy": {
                "mode": "chat",
                "input_cost_per_token": 1e-07,
                "output_cost_per_token": 9e-06,
            },
            "terse": {
                "mode": "chat",
                "input_cost_per_token": 5e-07,
                "output_cost_per_token": 5e-07,
            },
        }
        need = {**self.need, "input_tokens": 10, "max_output": 4000}
        routes = [remote("wordy", model="wordy"), remote("terse", model="terse")]
        self.assertEqual(
            self.hook.decide(
                self.eligible(routes, need, catalog), need, strategy="weighted"
            ),
            "terse",
            "the cheaper input price belongs to the route that would bill far "
            "more once the answer is counted",
        )


class TestLocalOnly(HookCase, unittest.TestCase):
    """A prompt can carry a credential, so it stays in the cluster by default."""

    BIG: ClassVar[dict] = {"model": ALIAS, "messages": [{"content": "x" * 30000}]}
    SECRET: ClassVar[dict] = {
        "model": ALIAS,
        "messages": [{"content": "deploy with sk-abcdefghijklmnopqrstuvwxyz012345"}],
    }

    def route(self, hook, data, routes):
        import asyncio

        proxy = types.ModuleType("litellm.proxy.proxy_server")
        proxy.llm_router = types.SimpleNamespace(model_list=routes)
        sys.modules["litellm.proxy"] = types.ModuleType("litellm.proxy")
        sys.modules["litellm.proxy.proxy_server"] = proxy
        return asyncio.run(
            hook.instance.async_pre_call_hook(None, None, dict(data), "completion")
        )

    def test_a_secret_shape_is_recognised(self) -> None:
        self.assertTrue(self.hook.carries_secret(self.SECRET))

    def test_ordinary_prose_is_not(self) -> None:
        self.assertFalse(
            self.hook.carries_secret(
                {"messages": [{"content": "my password is weak"}]}
            ),
            "a pattern that matches prose teaches callers to ignore the refusal",
        )

    def test_a_secret_stays_local_when_a_local_route_can_take_it(self) -> None:
        routes = [local("home", context=99999), remote("big", context=99999)]
        self.assertEqual(self.route(self.hook, self.SECRET, routes)["model"], "home")

    def test_by_default_a_big_prompt_does_not_leave_the_cluster(self) -> None:
        routes = [local("tiny", context=10), remote("big", context=99999)]
        verdict = self.route(self.hook, self.BIG, routes)
        self.assertIsInstance(verdict, str)
        self.assertIn("router_remote_fallback", verdict)

    def test_the_switch_lets_a_big_prompt_reach_a_remote_model(self) -> None:
        hook = load(remote_fallback=True)
        routes = [local("tiny", context=10), remote("big", context=99999)]
        self.assertEqual(self.route(hook, self.BIG, routes)["model"], "big")

    def test_the_switch_does_not_unlock_a_secret(self) -> None:
        hook = load(remote_fallback=True)
        routes = [local("tiny", context=10), remote("big", context=99999)]
        verdict = self.route(hook, self.SECRET, routes)
        self.assertIsInstance(verdict, str)
        self.assertIn("structured secret", verdict)


class TestLoudFailure(HookCase, unittest.TestCase):
    """A router that cannot route says so; it never answers from a default."""

    def route(self, routes, data):
        import asyncio

        proxy = types.ModuleType("litellm.proxy.proxy_server")
        proxy.llm_router = types.SimpleNamespace(model_list=routes)
        sys.modules["litellm.proxy"] = types.ModuleType("litellm.proxy")
        sys.modules["litellm.proxy.proxy_server"] = proxy
        return asyncio.run(
            self.hook.instance.async_pre_call_hook(None, None, dict(data), "completion")
        )

    def test_a_request_for_another_model_is_not_touched(self) -> None:
        self.assertIsNone(self.route([local("x")], {"model": "x"}))

    def test_no_eligible_model_is_rejected_with_the_demand(self) -> None:
        verdict = self.route(
            [local("tiny", context=1)],
            {"model": ALIAS, "messages": [{"content": "x" * 9000}]},
        )
        self.assertIsInstance(verdict, str)
        self.assertIn("cannot route", verdict)

    def test_a_routable_request_is_rewritten(self) -> None:
        verdict = self.route(
            [local("big", context=99999)],
            {"model": ALIAS, "messages": [{"content": "hi"}]},
        )
        self.assertEqual(verdict["model"], "big")


class TestConventionalStrategy(HookCase, unittest.TestCase):
    def test_the_cheapest_price_wins(self) -> None:
        routes = [
            remote("pricey", model="claude-sonnet-4-5"),
            remote("cheap", model="openai/gpt-4o-mini"),
        ]
        self.assertEqual(self.decide(routes), "cheap")

    def test_a_local_model_beats_every_paid_one(self) -> None:
        self.assertEqual(
            self.decide([remote("paid", model="openai/gpt-4o-mini"), local("home")]),
            "home",
        )

    def test_a_local_model_wins_even_when_a_remote_one_is_cheaper(self) -> None:
        routes = [
            remote("free-tier", traits={"input_cost": 0.0, "output_cost": 0.0}),
            local("home", traits={"input_cost": 9.9, "output_cost": 9.9}),
        ]
        self.assertEqual(
            self.decide(routes),
            "home",
            "a prompt can carry a credential, so locality outranks price",
        )

    def test_a_mock_counts_as_local(self) -> None:
        self.assertEqual(
            self.decide([remote("paid", model="openai/gpt-4o-mini"), mock("mock/x")]),
            "mock/x",
        )

    def test_among_equal_cost_the_faster_declared_route_wins(self) -> None:
        self.assertEqual(
            self.decide(
                [
                    local("slow", traits={"speed": 12}),
                    local("fast", traits={"speed": 90}),
                ]
            ),
            "fast",
        )

    def test_a_tie_is_broken_by_alias_so_a_rerun_repeats(self) -> None:
        routes = [local("b"), local("a")]
        first = self.decide(routes)
        second = self.decide(list(reversed(routes)))
        self.assertEqual((first, second), ("a", "a"))

    def test_a_caching_route_outranks_an_equal_one_without(self) -> None:
        routes = [
            remote(
                "plain",
                model="claude-sonnet-4-5",
                traits={"input_cost": 0.0, "output_cost": 0.0},
            ),
            remote(
                "cached",
                model="openai/gpt-4o-mini",
                traits={"input_cost": 0.0, "output_cost": 0.0},
            ),
        ]
        self.assertEqual(self.decide(routes), "cached")

    def test_the_prompt_does_not_change_the_weighted_order(self) -> None:
        routes = [
            local("small", context=8192, traits={"speed": 5}),
            local("big", context=99999, traits={"speed": 90}),
        ]
        small = self.decide(routes, {**self.need, "input_tokens": 10})
        large = self.decide(routes, {**self.need, "input_tokens": 4000})
        self.assertEqual((small, large), ("big", "big"))


class JeffStub:
    """Stands in for the jeff server, recording what the router asked it.

    Args:
        choice: the alias jeff answers with, or None to raise a transport error.
        confidence: the confidence it reports alongside the choice.
    """

    def __init__(self, choice, confidence=0.9) -> None:
        self.choice = choice
        self.confidence = confidence
        self.seen: dict = {}

    def urlopen(self, request, timeout=None):
        if self.choice is None:
            raise OSError("connection refused")
        self.seen = {
            "url": request.full_url,
            "timeout": timeout,
            "headers": {k.lower(): v for k, v in request.header_items()},
            "body": json.loads(request.data.decode()),
        }
        body = {
            "model": "gliformer-large-v1",
            "answers": {
                "route": {
                    "type": "choice",
                    "choice": self.choice,
                    "confidence": self.confidence,
                    "probabilities": {self.choice: self.confidence},
                }
            },
            "usage": {"input_tokens": 12, "output_tokens": 1},
        }
        return _Response(json.dumps(body).encode())


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


class TestSystemOneStrategy(HookCase, unittest.TestCase):
    """The prompt goes to jeff, which answers one typed choice."""

    ROUTES: ClassVar[list] = [
        local("small", context=4096),
        local("large", context=131072),
    ]

    def ask(self, stub, routes=None, need=None, text="pick one"):
        need = need or self.need
        with unittest.mock.patch("urllib.request.urlopen", stub.urlopen):
            return self.hook.decide(
                self.eligible(routes or self.ROUTES, need),
                need,
                text,
                strategy="system_one",
            )

    def test_the_alias_jeff_chooses_is_the_one_routed_to(self) -> None:
        self.assertEqual(self.ask(JeffStub("large")), "large")
        self.assertEqual(self.ask(JeffStub("small")), "small")

    def test_the_candidates_become_the_choice_options(self) -> None:
        stub = JeffStub("small")
        self.ask(stub)
        question = stub.seen["body"]["questions"]["route"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(sorted(question["criteria"]), ["large", "small"])

    def test_the_prompt_is_the_state_it_classifies(self) -> None:
        stub = JeffStub("small")
        self.ask(stub, text="summarise this invoice")
        self.assertEqual(stub.seen["body"]["state"], "summarise this invoice")

    def test_the_request_carries_the_model_alias_and_the_bearer_key(self) -> None:
        stub = JeffStub("small")
        self.ask(stub)
        self.assertEqual(stub.seen["body"]["model"], "jev-latest")
        self.assertEqual(stub.seen["headers"]["authorization"], "Bearer jeff-test-key")
        self.assertEqual(stub.seen["url"], f"{JEFF_URL}/v1/systemone")

    def test_a_long_prompt_is_truncated_to_what_the_server_accepts(self) -> None:
        stub = JeffStub("small")
        self.ask(stub, text="x" * 50000)
        self.assertEqual(
            len(stub.seen["body"]["state"]),
            self.hook.JEFF_MAX_STATE_CHARS,
            "the server answers 422 above its state limit, which would read as "
            "a routing failure rather than an oversized prompt",
        )

    def test_an_option_the_router_never_offered_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.ask(JeffStub("a-model-nobody-serves"))

    def test_the_prompt_changes_the_choice_where_weights_cannot(self) -> None:
        need = {**self.need, "input_tokens": 10}
        self.assertEqual(
            self.hook.decide(
                self.eligible(self.ROUTES, need), need, strategy="weighted"
            ),
            "large",
        )
        self.assertEqual(self.ask(JeffStub("small"), need=need), "small")

    def test_the_render_carries_the_strategy(self) -> None:
        self.assertEqual(load(strategy="system_one").ROUTER_STRATEGY, "system_one")

    def test_an_unreachable_decider_rejects_rather_than_substituting_one(self) -> None:
        hook = load(strategy="system_one")
        stub = JeffStub(None)
        with unittest.mock.patch("urllib.request.urlopen", stub.urlopen):
            verdict = TestLoudFailure.route(
                types.SimpleNamespace(hook=hook),
                [local("small", context=4096), local("large", context=131072)],
                {"model": ALIAS, "messages": [{"content": "hi"}]},
            )
        self.assertIsInstance(
            verdict,
            str,
            "falling back to another decider would make the alias mean "
            "something the caller did not ask for",
        )
        self.assertIn("could not reach a decision", verdict)


class TestShippedConfiguration(HookCase, unittest.TestCase):
    SPEED_ONLY: ClassVar[dict] = {"locality": 0.0, "cost": 0.0, "speed": 1.0}

    def test_the_render_carries_the_shipped_weights(self) -> None:
        self.assertEqual(self.hook.ROUTER_WEIGHTS, SHIPPED_WEIGHTS)

    def test_the_shipped_strategy_reads_the_jeff_service_flag(self) -> None:
        self.assertIn(
            "services.jeff.enabled",
            SHIPPED["router_strategy"],
            "the strategy follows whether the System One service is deployed, "
            "and it reads that from the one flag that decides it",
        )

    def test_both_strategy_names_are_reachable_from_the_expression(self) -> None:
        env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - a config value, not markup
        env.filters["bool"] = bool
        template = env.from_string(SHIPPED["router_strategy"])
        self.assertEqual(template.render(lookup=lambda *_args: True), "system_one")
        self.assertEqual(
            template.render(lookup=lambda *_args: False),
            "weighted",
            "without the System One service there is nothing to ask, so the "
            "gateway must fall to the strategy it can compute itself",
        )

    def test_the_shipped_weights_keep_locality_decisive(self) -> None:
        others = sum(v for k, v in SHIPPED_WEIGHTS.items() if k != "locality")
        self.assertGreater(
            SHIPPED_WEIGHTS["locality"],
            others,
            "every other factor together must not reach locality, or the "
            "shipped default stops being the safest one",
        )

    def test_a_zero_weight_removes_the_factor(self) -> None:
        routes = [
            remote("pricey", model="claude-sonnet-4-5", traits={"speed": 99}),
            remote("cheap", model="openai/gpt-4o-mini", traits={"speed": 1}),
        ]
        self.assertEqual(self.decide(routes, weights={"cost": 1.0}), "cheap")
        self.assertEqual(self.decide(routes, weights=self.SPEED_ONLY), "pricey")

    def test_no_weighting_sends_a_secret_out_of_the_cluster(self) -> None:
        hook = load(remote_fallback=True, weights=self.SPEED_ONLY)
        routes = [
            local("home", context=99999, traits={"speed": 1}),
            remote("quick", context=99999, traits={"speed": 999}),
        ]
        verdict = TestLocalOnly.route(self, hook, TestLocalOnly.SECRET, routes)
        self.assertEqual(
            verdict["model"],
            "home",
            "the locality filter runs before the score, so a weight cannot buy "
            "a credential a trip to a provider",
        )


if __name__ == "__main__":
    unittest.main()
