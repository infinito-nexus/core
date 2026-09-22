"""The gateway config publishes one alias per model, whichever backend serves it.

``config.yaml.j2`` is where the two local backends meet: Ollama pulls a model
under the alias and LM Studio under its own hub name, and both must surface to
consumers as the same ``model_name``. A wrong accessor or a missing de-duplicate
condition does not fail the render, it publishes a route nothing answers, so the
template is rendered here rather than read.
"""

from __future__ import annotations

import unittest

import yaml
from jinja2 import Environment, StrictUndefined

from plugins.filter.merge.with_defaults import merge_with_defaults
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

TEMPLATE = PROJECT_ROOT / "roles/svc-ai-litellm/templates/config.yaml.j2"
REMOTE_MODELS = load_yaml(
    PROJECT_ROOT / "roles/svc-ai-litellm" / ROLE_FILE_META_SERVICES
)["litellm"]["remote_models"]
BONSAI = {
    "alias": "openrouter/ternary-bonsai-2-27b",
    "model": "openrouter/prism-ml/ternary-bonsai-2-27b",
    "provider": "openrouter",
}

SHARED = {"alias": "qwen2.5:0.5b", "name": "qwen2.5-0.5b-instruct"}
OLLAMA_ONLY = {"alias": "llama3:latest", "name": "llama-3.2-3b-instruct"}
LMSTUDIO_ONLY = {"alias": "mistral:latest", "name": "mistral-7b-instruct-v0.3"}

OLLAMA_URL = "http://ollama:11434"
LMSTUDIO_URL = "http://lmstudio:1234"


def _ansible_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return bool(value)


def _stub_lookup(ollama_models, lmstudio_models):
    def lookup(kind, role, path, *args):
        if (kind, path) == ("config", "services.ollama.preload_models"):
            return ollama_models
        if (kind, path) == ("config", "services.lmstudio.preload_models"):
            return lmstudio_models
        raise AssertionError(f"unexpected lookup({kind!r}, {role!r}, {path!r})")

    return lookup


def render(*, ollama=(), lmstudio=(), keys=None, remote_models=REMOTE_MODELS):
    """The rendered config as a parsed mapping.

    Args:
        ollama: preload entries svc-ai-ollama declares; empty means not deployed.
        lmstudio: preload entries svc-ai-lmstudio declares; empty means not deployed.
        keys: provider -> key value; a provider absent from it stays unkeyed.
        remote_models: the services.litellm.remote_models list in effect.
    """
    env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - YAML, not markup
    env.filters["bool"] = _ansible_bool
    rendered = env.from_string(read_text(str(TEMPLATE))).render(
        LITELLM_OLLAMA_BACKEND=str(bool(ollama)),
        LITELLM_LMSTUDIO_BACKEND=str(bool(lmstudio)),
        lookup=_stub_lookup(list(ollama), list(lmstudio)),
        OLLAMA_BASE_LOCAL_URL=OLLAMA_URL,
        LMSTUDIO_BASE_LOCAL_URL=LMSTUDIO_URL,
        LITELLM_MAX_OUTPUT_TOKENS=512,
        LITELLM_UPSTREAM_TIMEOUT=60,
        LITELLM_REMOTE_MODELS=list(remote_models),
        LITELLM_KEYED_PROVIDERS=[name for name, key in (keys or {}).items() if key],
    )
    return yaml.safe_load(
        rendered
    )  # nocheck: direct-yaml - parses this test's own render


def routes(config) -> dict:
    return {
        entry["model_name"]: entry["litellm_params"]
        for entry in (config.get("model_list") or [])
    }


class TestOllamaOnly(unittest.TestCase):
    def test_every_alias_is_published_against_the_ollama_backend(self) -> None:
        published = routes(render(ollama=[SHARED, OLLAMA_ONLY]))
        self.assertEqual(set(published), {SHARED["alias"], OLLAMA_ONLY["alias"]})
        self.assertEqual(
            published[SHARED["alias"]]["model"], f"ollama/{SHARED['alias']}"
        )
        self.assertEqual(published[SHARED["alias"]]["api_base"], OLLAMA_URL)


class TestLmstudioOnly(unittest.TestCase):
    def test_the_alias_is_published_against_the_lmstudio_name(self) -> None:
        published = routes(render(lmstudio=[SHARED, LMSTUDIO_ONLY]))
        self.assertEqual(set(published), {SHARED["alias"], LMSTUDIO_ONLY["alias"]})
        self.assertEqual(
            published[SHARED["alias"]]["model"], f"openai/{SHARED['name']}"
        )
        self.assertEqual(published[SHARED["alias"]]["api_base"], f"{LMSTUDIO_URL}/v1")

    def test_an_alias_reaches_the_same_name_ollama_would_publish(self) -> None:
        self.assertEqual(
            set(routes(render(lmstudio=[SHARED]))),
            set(routes(render(ollama=[SHARED]))),
        )


class TestBothBackends(unittest.TestCase):
    def test_a_shared_alias_is_published_once_and_routed_to_ollama(self) -> None:
        published = routes(
            render(ollama=[SHARED, OLLAMA_ONLY], lmstudio=[SHARED, LMSTUDIO_ONLY])
        )
        self.assertEqual(
            set(published),
            {SHARED["alias"], OLLAMA_ONLY["alias"], LMSTUDIO_ONLY["alias"]},
        )
        self.assertEqual(published[SHARED["alias"]]["api_base"], OLLAMA_URL)
        self.assertEqual(
            published[LMSTUDIO_ONLY["alias"]]["api_base"], f"{LMSTUDIO_URL}/v1"
        )


class TestNoBackend(unittest.TestCase):
    def test_the_model_list_is_empty(self) -> None:
        self.assertEqual(render()["model_list"], [])

    def test_one_provider_key_alone_publishes_its_route(self) -> None:
        published = routes(render(keys={"openrouter": "sk-or-test"}))
        self.assertEqual(set(published), {"openrouter/auto"})
        self.assertEqual(
            published["openrouter/auto"]["api_key"], "os.environ/OPENROUTER_API_KEY"
        )

    def test_each_keyed_provider_gets_its_own_route(self) -> None:
        published = routes(
            render(keys={"openai": "sk-test", "anthropic": "sk-ant-test"})
        )
        self.assertEqual(
            set(published), {"openai/gpt-4o-mini", "anthropic/claude-sonnet-4-5"}
        )

    def test_an_unkeyed_provider_publishes_nothing(self) -> None:
        self.assertEqual(render(keys={"openai": ""})["model_list"], [])


class TestConfiguredRemoteModels(unittest.TestCase):
    def test_an_added_model_shares_its_provider_key(self) -> None:
        published = routes(
            render(
                keys={"openrouter": "sk-or-test"},
                remote_models=[*REMOTE_MODELS, BONSAI],
            )
        )
        self.assertEqual(set(published), {"openrouter/auto", BONSAI["alias"]})
        self.assertEqual(published[BONSAI["alias"]]["model"], BONSAI["model"])
        self.assertEqual(
            published[BONSAI["alias"]]["api_key"], "os.environ/OPENROUTER_API_KEY"
        )

    def test_an_inventory_list_replaces_the_defaults(self) -> None:
        merged = merge_with_defaults(
            {
                "svc-ai-litellm": {
                    "services": {"litellm": {"remote_models": REMOTE_MODELS}}
                }
            },
            {"svc-ai-litellm": {"services": {"litellm": {"remote_models": [BONSAI]}}}},
        )
        published = routes(
            render(
                keys={"openrouter": "sk-or-test"},
                remote_models=merged["svc-ai-litellm"]["services"]["litellm"][
                    "remote_models"
                ],
            )
        )
        self.assertEqual(set(published), {BONSAI["alias"]})


if __name__ == "__main__":
    unittest.main()
