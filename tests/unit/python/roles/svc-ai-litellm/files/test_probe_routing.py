"""Unit tests for the svc-ai-litellm routing probe's verdict logic."""

from __future__ import annotations

import importlib.util
import unittest
from typing import ClassVar

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/svc-ai-litellm/files/test/probe.py"

spec = importlib.util.spec_from_file_location("litellm_probe", MODULE_PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

ALIAS = "qwen2.5:0.5b"
LMSTUDIO_ONLY = "mistral:latest"


def verdict(**overrides) -> list[str]:
    kwargs = {
        "served": set(),
        "expected": [],
        "chat_model": "",
        "chat_model_served": False,
        "ollama_enabled": False,
        "lmstudio_enabled": False,
        "lmstudio_aliases": [LMSTUDIO_ONLY],
        "remote_aliases": [],
    }
    kwargs.update(overrides)
    return probe.evaluate(**kwargs)


class TestOllamaOnlyDeployment(unittest.TestCase):
    """svc-ai-ollama deployed, svc-ai-lmstudio not — variant 0."""

    def test_a_consistent_gateway_passes(self) -> None:
        self.assertEqual(
            verdict(
                served={ALIAS},
                expected=[ALIAS],
                chat_model=ALIAS,
                chat_model_served=True,
                ollama_enabled=True,
            ),
            [],
        )

    def test_an_lmstudio_alias_without_its_backend_fails(self) -> None:
        failures = verdict(
            served={ALIAS, LMSTUDIO_ONLY},
            expected=[ALIAS],
            chat_model=ALIAS,
            chat_model_served=True,
            ollama_enabled=True,
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("svc-ai-lmstudio is not deployed", failures[0])

    def test_a_declared_model_the_gateway_dropped_fails(self) -> None:
        failures = verdict(
            served=set(),
            expected=[ALIAS],
            chat_model=ALIAS,
            chat_model_served=True,
            ollama_enabled=True,
        )
        self.assertTrue(
            any("does not serve" in failure for failure in failures), failures
        )

    def test_the_model_consumers_ask_for_must_be_routable(self) -> None:
        failures = verdict(
            served={ALIAS},
            expected=[ALIAS],
            chat_model="llama3:latest",
            chat_model_served=True,
            ollama_enabled=True,
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("llama3:latest", failures[0])


class TestLmstudioOnlyDeployment(unittest.TestCase):
    """svc-ai-lmstudio deployed, svc-ai-ollama not — variant 2."""

    def test_the_same_alias_ollama_would_serve_passes(self) -> None:
        self.assertEqual(
            verdict(
                served={ALIAS},
                expected=[ALIAS],
                chat_model=ALIAS,
                chat_model_served=True,
                lmstudio_enabled=True,
                lmstudio_aliases=[ALIAS],
            ),
            [],
        )

    def test_a_declared_alias_the_gateway_never_routed_fails(self) -> None:
        failures = verdict(
            served=set(),
            expected=[ALIAS],
            chat_model=ALIAS,
            chat_model_served=True,
            lmstudio_enabled=True,
            lmstudio_aliases=[ALIAS],
        )
        self.assertTrue(
            any("declared and not routed" in failure for failure in failures), failures
        )

    def test_an_ollama_model_without_its_backend_fails(self) -> None:
        failures = verdict(
            served={ALIAS, "llama3:latest"},
            expected=[ALIAS],
            chat_model=ALIAS,
            chat_model_served=True,
            lmstudio_enabled=True,
            lmstudio_aliases=[ALIAS],
        )
        self.assertTrue(
            any("svc-ai-ollama is not deployed" in failure for failure in failures),
            failures,
        )


class TestBothBackendsDeployment(unittest.TestCase):
    """Variant 0 plus lmstudio: a shared alias proves nothing about lmstudio."""

    def test_only_the_exclusive_alias_is_demanded(self) -> None:
        self.assertEqual(
            verdict(
                served={ALIAS, LMSTUDIO_ONLY},
                expected=[ALIAS, LMSTUDIO_ONLY],
                chat_model=ALIAS,
                chat_model_served=True,
                ollama_enabled=True,
                lmstudio_enabled=True,
            ),
            [],
        )

    def test_a_missing_exclusive_alias_still_fails(self) -> None:
        failures = verdict(
            served={ALIAS},
            expected=[ALIAS],
            chat_model=ALIAS,
            chat_model_served=True,
            ollama_enabled=True,
            lmstudio_enabled=True,
        )
        self.assertTrue(
            any("declared and not routed" in failure for failure in failures), failures
        )


class TestRemoteProviders(unittest.TestCase):
    """A configured provider key publishes its alias and serves the gateway."""

    def test_a_keyed_provider_is_the_only_backend_needed(self) -> None:
        self.assertEqual(
            verdict(
                served={"openai/gpt-4o-mini"},
                expected=["openai/gpt-4o-mini"],
                chat_model="openai/gpt-4o-mini",
                chat_model_served=True,
                remote_aliases=["openai/gpt-4o-mini"],
            ),
            [],
        )

    def test_a_remote_alias_is_not_mistaken_for_an_ollama_model(self) -> None:
        self.assertEqual(
            verdict(
                served={"anthropic/claude-sonnet-4-5", ALIAS},
                expected=["anthropic/claude-sonnet-4-5", ALIAS],
                chat_model=ALIAS,
                chat_model_served=True,
                lmstudio_enabled=True,
                lmstudio_aliases=[ALIAS],
                remote_aliases=["anthropic/claude-sonnet-4-5"],
            ),
            [],
        )

    def test_a_declared_provider_the_gateway_dropped_fails(self) -> None:
        failures = verdict(
            served=set(),
            expected=["openrouter/auto"],
            chat_model="openrouter/auto",
            chat_model_served=True,
            remote_aliases=["openrouter/auto"],
        )
        self.assertTrue(
            any("does not serve" in failure for failure in failures), failures
        )


class TestNoBackendDeployment(unittest.TestCase):
    def test_an_empty_gateway_passes(self) -> None:
        self.assertEqual(verdict(), [])

    def test_any_published_model_fails(self) -> None:
        failures = verdict(served={"openrouter/auto"})
        self.assertTrue(
            any("no backend is deployed" in failure for failure in failures), failures
        )

    def test_the_chat_model_is_not_demanded_when_nothing_serves_it(self) -> None:
        self.assertEqual(verdict(chat_model=ALIAS), [])


class TestRouterAlias(unittest.TestCase):
    """The router alias is served by no backend, so it is accounted separately."""

    def test_a_served_router_alias_is_not_read_as_an_unbacked_route(self) -> None:
        self.assertEqual(
            verdict(
                served={ALIAS, "auto"},
                expected=[ALIAS, "auto"],
                chat_model=ALIAS,
                chat_model_served=True,
                ollama_enabled=True,
                router_alias="auto",
            ),
            [],
        )

    def test_a_declared_router_alias_the_gateway_withholds_fails(self) -> None:
        failures = verdict(
            served={ALIAS},
            expected=[ALIAS],
            chat_model=ALIAS,
            chat_model_served=True,
            ollama_enabled=True,
            router_alias="auto",
        )
        self.assertTrue(
            any("router alias 'auto'" in failure for failure in failures), failures
        )


class TestRouteVerdict(unittest.TestCase):
    """An answer is only evidence of routing when it names a model that fits."""

    WINDOWS: ClassVar[dict] = {"small": 4096, "medium": 16384, "large": 65536}

    MOCKS: ClassVar[tuple] = ("medium",)

    def verdict(self, served, needed=5461, counted=0, sent=0, mocks=()):
        return probe.route_verdict(
            "auto", self.WINDOWS, served, needed, counted, sent, mocks
        )

    def test_a_backend_that_evaluated_less_than_was_sent_fails(self) -> None:
        self.assertIn(
            "silently dropped the rest",
            self.verdict("medium", counted=4098, sent=8192),
            "ollama truncates a prompt past the trained window instead of "
            "refusing it, and reports only the tokens it kept, so the declared "
            "window cannot show the loss",
        )

    def test_a_backend_that_evaluated_everything_passes(self) -> None:
        self.assertEqual(self.verdict("large", counted=8227, sent=8192), "")

    def test_a_backend_that_reports_no_usage_is_not_accused(self) -> None:
        self.assertEqual(self.verdict("large", counted=0, sent=8192), "")

    def test_a_tokenizer_disagreeing_by_a_few_tokens_is_not_truncation(self) -> None:
        self.assertEqual(
            self.verdict("large", counted=8185, sent=8192),
            "",
            "a chat template shifts the total either way, so an exact "
            "comparison would fail a healthy route",
        )

    def test_a_mock_is_not_accused_of_truncating(self) -> None:
        self.assertEqual(
            self.verdict("medium", counted=10, sent=8192, mocks=self.MOCKS),
            "",
            "litellm answers a mock route from a canned string and reports its "
            "own constant prompt token count, so the number carries nothing to "
            "compare the prompt against",
        )

    def test_a_mock_is_still_held_to_its_declared_window(self) -> None:
        self.assertIn(
            "did not exclude it",
            self.verdict("small", needed=8192, counted=10, sent=8192, mocks=("small",)),
            "the exemption covers the truncation number only; a mock routed a "
            "prompt its declared window cannot hold is still a routing failure, "
            "which is why the exemption sits after the window check",
        )

    def test_an_alias_outside_the_mock_list_is_still_accused(self) -> None:
        self.assertIn(
            "silently dropped the rest",
            self.verdict("medium", counted=10, sent=8192, mocks=("other",)),
        )

    def test_a_model_whose_window_holds_the_prompt_passes(self) -> None:
        self.assertEqual(self.verdict("medium"), "")

    def test_answering_as_the_alias_itself_fails(self) -> None:
        self.assertIn("did not rewrite", self.verdict("auto"))

    def test_naming_no_model_fails(self) -> None:
        self.assertIn("without naming a model", self.verdict(""))

    def test_a_window_too_small_for_the_prompt_fails(self) -> None:
        self.assertIn("did not exclude it", self.verdict("small"))

    def test_an_undeclared_window_is_not_second_guessed(self) -> None:
        self.assertEqual(self.verdict("openrouter/auto"), "")

    def test_a_provider_prefixed_answer_is_matched_to_its_window(self) -> None:
        self.assertIn(
            "did not exclude it",
            self.verdict("ollama/small"),
            "litellm names the resolved model, not the alias, so a literal "
            "lookup would miss the window and pass every answer",
        )

    def test_a_provider_prefixed_answer_that_fits_passes(self) -> None:
        self.assertEqual(self.verdict("ollama/large"), "")


SHIPPED_MIN_CHARS_PER_TOKEN = load_yaml(
    PROJECT_ROOT / "roles/svc-ai-litellm" / ROLE_FILE_META_SERVICES
)["litellm"]["router"]["min_chars_per_token"]


class TestOversizedPrompt(unittest.TestCase):
    """The prompt has to clear the smallest window by the hook's own floor."""

    def test_the_demand_exceeds_the_window_it_targets(self) -> None:
        _, needed = probe.oversized_prompt(4096, SHIPPED_MIN_CHARS_PER_TOKEN)
        self.assertGreater(needed, 4096)

    def test_the_demand_stays_inside_the_next_window_up(self) -> None:
        _, needed = probe.oversized_prompt(4096, SHIPPED_MIN_CHARS_PER_TOKEN)
        self.assertLess(needed, 65536)

    def test_the_demand_matches_what_the_prompt_really_tokenizes_to(self) -> None:
        prompt, needed = probe.oversized_prompt(4096, SHIPPED_MIN_CHARS_PER_TOKEN)
        self.assertGreaterEqual(
            needed,
            len(prompt) // 2,
            "'x ' costs one token per two characters on every tokenizer served "
            "here, so a demand computed on a larger divisor understates the "
            "prompt and admits a model that cannot hold it",
        )


if __name__ == "__main__":
    unittest.main()
