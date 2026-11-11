from __future__ import annotations

import unittest

from . import load

environment = load("environment")
persona = load("persona")

ENV = {
    "ASSISTANT_DATABASE_USER": "assistant",
    "ASSISTANT_DATABASE_PASSWORD": "p@ss/word",
    "ASSISTANT_DATABASE_HOST": "postgres",
    "ASSISTANT_DATABASE_PORT": "5432",
    "ASSISTANT_DATABASE_NAME": "assistant",
    "ASSISTANT_ADMIN_GROUP": "/roles/web-svc-assistant/administrator",
    "ASSISTANT_THRESHOLD": "0.55",
    "ASSISTANT_PASSAGES": "4",
    "ASSISTANT_MAX_CHARS": "500",
    "ASSISTANT_MODEL_END_USER": "end-user:1.0.0",
    "ASSISTANT_MODEL_CONSULTANT": "consultant:1.0.0",
    "ASSISTANT_MODEL_EMBEDDING": "embedding:1.0.0",
    "ASSISTANT_MODEL_KEY": "sk-assistant",
    "ASSISTANT_MODEL_TIMEOUT": "60",
    "ASSISTANT_MODEL_URL": "http://litellm:4000/v1",
}


class TestEnvironment(unittest.TestCase):
    def test_a_password_with_url_characters_stays_in_its_part(self) -> None:
        self.assertEqual(
            environment.dsn(ENV),
            "postgresql://assistant:p%40ss%2Fword@postgres:5432/assistant",
        )

    def test_the_settings_are_typed(self) -> None:
        settings = environment.settings(ENV)
        self.assertEqual(
            (settings.threshold, settings.passages, settings.max_chars), (0.55, 4, 500)
        )

    def test_each_persona_has_its_model(self) -> None:
        self.assertEqual(
            environment.chat_models(ENV),
            {
                persona.END_USER: "end-user:1.0.0",
                persona.CONSULTANT: "consultant:1.0.0",
            },
        )

    def test_an_unpinned_model_stops_the_service_from_starting(self) -> None:
        with self.assertRaises(ValueError):
            environment.models({**ENV, "ASSISTANT_MODEL_EMBEDDING": ""})

    def test_the_pinned_models_build_a_gateway_client(self) -> None:
        self.assertIsInstance(environment.models(ENV), environment.Models)


if __name__ == "__main__":
    unittest.main()
