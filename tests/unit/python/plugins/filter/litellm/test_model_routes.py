from __future__ import annotations

import unittest

from plugins.filter.litellm.model_routes import litellm_model_routes

OLLAMA_URL = "http://ollama:11434"
LMSTUDIO_URL = "http://lmstudio:1234"

SHARED = {"alias": "qwen2.5:0.5b", "name": "qwen2.5-0.5b-instruct", "context": 32768}
LMSTUDIO_ONLY = {"alias": "mistral:latest", "name": "mistral-7b-instruct-v0.3"}
REMOTE = {
    "alias": "openrouter/auto",
    "model": "openrouter/openrouter/auto",
    "provider": "openrouter",
}
MOCK = {
    "alias": "mock/deterministic",
    "provider": "mock",
    "response": "pong",
    "context": 131072,
}


def routes(ollama=(), lmstudio=(), declared=()):
    return litellm_model_routes(
        list(ollama),
        list(lmstudio),
        list(declared),
        ollama_url=OLLAMA_URL,
        lmstudio_url=LMSTUDIO_URL,
        max_tokens=512,
        timeout=60,
    )


def by_alias(built):
    return {route["alias"]: route for route in built}


class TestPublicationOrder(unittest.TestCase):
    """The first route is what LITELLM_CHAT_MODEL names, so order is a contract."""

    def test_a_local_model_outranks_a_declared_one(self) -> None:
        built = routes(ollama=[SHARED], declared=[MOCK, REMOTE])
        self.assertEqual(next(route["alias"] for route in built), SHARED["alias"])

    def test_declared_models_keep_their_declaration_order(self) -> None:
        built = routes(declared=[MOCK, REMOTE])
        self.assertEqual(
            [route["alias"] for route in built], [MOCK["alias"], REMOTE["alias"]]
        )

    def test_nothing_declared_publishes_nothing(self) -> None:
        self.assertEqual(routes(), [])


class TestLocalBackends(unittest.TestCase):
    def test_ollama_is_called_through_its_own_scheme(self) -> None:
        params = by_alias(routes(ollama=[SHARED]))[SHARED["alias"]]["params"]
        self.assertEqual(params["model"], f"ollama/{SHARED['alias']}")
        self.assertEqual(params["api_base"], OLLAMA_URL)

    def test_a_declared_window_reaches_the_backend_and_the_model_info(self) -> None:
        route = by_alias(routes(ollama=[SHARED]))[SHARED["alias"]]
        self.assertEqual(route["params"]["num_ctx"], SHARED["context"])
        self.assertEqual(route["context"], SHARED["context"])

    def test_a_model_without_a_window_sets_no_num_ctx(self) -> None:
        route = by_alias(routes(lmstudio=[LMSTUDIO_ONLY]))[LMSTUDIO_ONLY["alias"]]
        self.assertNotIn("num_ctx", route["params"])
        self.assertIsNone(route["context"])

    def test_lmstudio_publishes_the_window_it_declares(self) -> None:
        route = by_alias(routes(lmstudio=[SHARED]))[SHARED["alias"]]
        self.assertEqual(
            route["context"],
            SHARED["context"],
            "the LM Studio branch used to drop the window its README promised",
        )

    def test_an_alias_both_backends_serve_is_published_once_by_ollama(self) -> None:
        built = routes(ollama=[SHARED], lmstudio=[SHARED, LMSTUDIO_ONLY])
        self.assertEqual(
            [route["alias"] for route in built],
            [SHARED["alias"], LMSTUDIO_ONLY["alias"]],
        )
        self.assertEqual(
            by_alias(built)[SHARED["alias"]]["params"]["api_base"], OLLAMA_URL
        )


class TestDeclaredModels(unittest.TestCase):
    def test_a_provider_route_reads_its_key_from_the_environment(self) -> None:
        params = by_alias(routes(declared=[REMOTE]))[REMOTE["alias"]]["params"]
        self.assertEqual(params["api_key"], "os.environ/OPENROUTER_API_KEY")
        self.assertEqual(params["model"], REMOTE["model"])

    def test_a_mock_answers_from_its_own_response(self) -> None:
        params = by_alias(routes(declared=[MOCK]))[MOCK["alias"]]["params"]
        self.assertEqual(params["mock_response"], MOCK["response"])

    def test_a_mock_names_no_upstream_to_call(self) -> None:
        params = by_alias(routes(declared=[MOCK]))[MOCK["alias"]]["params"]
        self.assertNotIn("api_base", params)
        self.assertNotIn(
            "timeout", params, "a mock cannot time out against a backend it never calls"
        )

    def test_a_mock_publishes_its_window(self) -> None:
        self.assertEqual(
            by_alias(routes(declared=[MOCK]))[MOCK["alias"]]["context"], MOCK["context"]
        )


if __name__ == "__main__":
    unittest.main()
