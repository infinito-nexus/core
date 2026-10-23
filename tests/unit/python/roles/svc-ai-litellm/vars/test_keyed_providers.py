"""The provider list the gateway actually publishes from.

A model whose provider is missing here is filtered out of the model list, and
the proxy then answers HTTP 400 for it while every name-level variable still
resolves to it. That combination cost a deploy: the chat model resolved to the
mock and the gateway served `model_list: []`.
"""

from __future__ import annotations

import ast
import unittest
from typing import ClassVar

from jinja2 import Environment, StrictUndefined

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_ROLE_VARS = PROJECT_ROOT / "roles/svc-ai-litellm" / ROLE_FILE_VARS_MAIN
_MOCK = "mock"


class TestProviderLists(unittest.TestCase):
    """Two lists that mean different things and are easy to confuse."""

    source: ClassVar[dict]

    @classmethod
    def setUpClass(cls):
        cls.source = load_yaml(str(_ROLE_VARS))

    def _render(self, name, provider_keys, keyed=None):
        env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders a Python list literal, not markup
        env.filters["dict2items"] = lambda mapping: [
            {"key": key, "value": value} for key, value in mapping.items()
        ]
        return ast.literal_eval(
            env.from_string(self.source[name]).render(
                LITELLM_PROVIDER_KEYS=provider_keys,
                LITELLM_KEYED_PROVIDERS=keyed if keyed is not None else [],
                AI_MOCK_PROVIDER=_MOCK,
            )
        )

    def _keyed(self, provider_keys):
        return self._render("LITELLM_KEYED_PROVIDERS", provider_keys)

    def test_a_provider_without_a_key_is_not_keyed(self) -> None:
        self.assertNotIn("openai", self._keyed({"openai": "", "anthropic": "sk-x"}))

    def test_a_provider_with_a_key_is_keyed(self) -> None:
        self.assertIn("anthropic", self._keyed({"openai": "", "anthropic": "sk-x"}))

    def test_the_mock_is_never_keyed(self) -> None:
        self.assertNotIn(
            _MOCK,
            self._keyed({"openai": "sk-x"}),
            "env.j2 emits <PROVIDER>_API_KEY for every keyed provider by indexing "
            "LITELLM_PROVIDER_KEYS, so a keyless entry here fails the render",
        )

    def test_the_mock_is_served_without_any_key(self) -> None:
        self.assertIn(
            _MOCK,
            self._render("LITELLM_SERVED_PROVIDERS", {}, keyed=[]),
            "a mock answers from its own response, so the model list must carry it",
        )

    def test_a_keyed_provider_is_also_served(self) -> None:
        self.assertIn(
            "anthropic",
            self._render("LITELLM_SERVED_PROVIDERS", {}, keyed=["anthropic"]),
        )


if __name__ == "__main__":
    unittest.main()
