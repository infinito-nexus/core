import re
import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

_AI_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "16_ai.yml"


def _stub_lookup(preload_models):
    def lookup(kind, role, path, *args):
        if (kind, path) == ("config", "services.ollama.preload_models"):
            return preload_models
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
        cls.source = load_yaml(_AI_VARS)

    def _render(self, name, *, roles, api_key, preload_models=()):
        return (
            self.env.from_string(self.source[name])
            .render(
                LITELLM_BACKEND_ROLES=list(roles),
                OPENROUTER_API_KEY=api_key,
                lookup=_stub_lookup(list(preload_models)),
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
        model, served = self._both(roles=["svc-ai-lmstudio"], api_key="")
        self.assertEqual(model, "lmstudio/default")
        self.assertEqual(served, "True")

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
            (["web-app-mattermost"], "", ()),
            (["web-app-mattermost"], "sk-test", ()),
            (["svc-ai-lmstudio"], "", ()),
            (["svc-ai-ollama"], "", ("llama3.2",)),
        )
        for roles, api_key, preload in cases:
            with self.subTest(roles=roles, api_key=bool(api_key)):
                model, served = self._both(
                    roles=roles, api_key=api_key, preload_models=preload
                )
                self.assertEqual(bool(model), served == "True")


if __name__ == "__main__":
    unittest.main()
