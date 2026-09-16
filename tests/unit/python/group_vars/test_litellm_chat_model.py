import re
import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

_AI_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "16_ai.yml"


def _ansible_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return bool(value)


def _stub_lookup(preload_models, lmstudio_models):
    def lookup(kind, role, path, *args):
        if (kind, path) == ("config", "services.ollama.preload_models"):
            return preload_models
        if (kind, path) == ("config", "services.lmstudio.preload_models"):
            return lmstudio_models
        raise AssertionError(f"unexpected lookup({kind!r}, {role!r}, {path!r})")

    return lookup


class TestLitellmChatModel(unittest.TestCase):
    """The gateway only publishes a model it has a backend for
    (roles/svc-ai-litellm/templates/config.yaml.j2). These expressions decide
    what consumers are told to ask for, so naming an unpublished model makes
    every prompt fail with a 400.
    """

    env: ClassVar[Environment]
    source: ClassVar[dict]

    @classmethod
    def setUpClass(cls):
        cls.env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
        cls.env.tests["search"] = lambda value, pattern: bool(
            re.search(pattern, str(value))
        )
        cls.env.filters["bool"] = _ansible_bool
        cls.source = load_yaml(_AI_VARS)

    def _render(self, name, *, roles, api_key, preload_models=(), lmstudio_models=()):
        return (
            self.env.from_string(self.source[name])
            .render(
                LITELLM_BACKEND_ROLES=list(roles),
                LITELLM_OLLAMA_BACKEND=str("svc-ai-ollama" in roles),
                LITELLM_LMSTUDIO_BACKEND=str("svc-ai-lmstudio" in roles),
                AI_REMOTE_ALIASES=(["openrouter/auto"] if api_key else []),
                lookup=_stub_lookup(
                    [{"alias": alias, "name": alias} for alias in preload_models],
                    [
                        {"alias": alias, "name": f"{alias}-gguf"}
                        for alias in lmstudio_models
                    ],
                ),
            )
            .strip()
        )

    def _both(self, **kwargs):
        return (
            self._render("LITELLM_CHAT_MODEL", **kwargs),
            self._render("LITELLM_CHAT_MODEL_SERVED", **kwargs),
        )

    def test_no_backend_and_no_key_names_no_model(self):
        model, served = self._both(roles=["web-app-mattermost"], api_key="")
        self.assertEqual(model, "")
        self.assertEqual(served, "False")

    def test_no_backend_with_a_key_uses_openrouter(self):
        model, served = self._both(roles=["web-app-mattermost"], api_key="sk-test")
        self.assertEqual(model, "openrouter/auto")
        self.assertEqual(served, "True")

    def test_lmstudio_wins_over_the_openrouter_fallback(self):
        model, served = self._both(
            roles=["svc-ai-lmstudio"], api_key="", lmstudio_models=["qwen2.5:0.5b"]
        )
        self.assertEqual(model, "qwen2.5:0.5b")
        self.assertEqual(served, "True")

    def test_lmstudio_without_a_preloaded_model_serves_nothing(self):
        served = self._render(
            "LITELLM_CHAT_MODEL_SERVED", roles=["svc-ai-lmstudio"], api_key=""
        )
        self.assertEqual(served, "False")

    def test_both_backends_name_the_same_model(self):
        alias = "qwen2.5:0.5b"
        with_ollama = self._render(
            "LITELLM_CHAT_MODEL",
            roles=["svc-ai-ollama"],
            api_key="",
            preload_models=[alias],
        )
        with_lmstudio = self._render(
            "LITELLM_CHAT_MODEL",
            roles=["svc-ai-lmstudio"],
            api_key="",
            lmstudio_models=[alias],
        )
        self.assertEqual(with_ollama, with_lmstudio)
        self.assertEqual(with_ollama, alias)

    def test_ollama_serves_its_first_non_embedding_model(self):
        model, served = self._both(
            roles=["svc-ai-ollama"],
            api_key="",
            preload_models=["nomic-embed-text", "llama3.2"],
        )
        self.assertEqual(model, "llama3.2")
        self.assertEqual(served, "True")

    def test_ollama_with_only_embedding_models_serves_nothing(self):
        served = self._render(
            "LITELLM_CHAT_MODEL_SERVED",
            roles=["svc-ai-ollama"],
            api_key="",
            preload_models=["nomic-embed-text"],
        )
        self.assertEqual(served, "False")

    def test_the_model_is_named_exactly_when_one_is_served(self):
        cases = (
            (["web-app-mattermost"], "", (), ()),
            (["web-app-mattermost"], "sk-test", (), ()),
            (["svc-ai-lmstudio"], "", (), ()),
            (["svc-ai-lmstudio"], "", (), ("qwen2.5:0.5b",)),
            (["svc-ai-ollama"], "", ("llama3.2",), ()),
        )
        for roles, api_key, preload, lmstudio in cases:
            with self.subTest(roles=roles, api_key=bool(api_key), lmstudio=lmstudio):
                model, served = self._both(
                    roles=roles,
                    api_key=api_key,
                    preload_models=preload,
                    lmstudio_models=lmstudio,
                )
                self.assertEqual(bool(model), served == "True")


if __name__ == "__main__":
    unittest.main()
