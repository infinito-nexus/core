import json
import unittest

import jinja2

from plugins.filter.dotenv import FilterModule
from utils import PROJECT_ROOT


class TestFreeLlmApiEnvironment(unittest.TestCase):
    def setUp(self):
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(PROJECT_ROOT),
            undefined=jinja2.StrictUndefined,
            autoescape=jinja2.select_autoescape(default_for_string=False),
        )
        self.env.filters["dotenv_quote"] = FilterModule().filters()["dotenv_quote"]
        self.env.filters["to_json"] = json.dumps
        self.template = self.env.get_template(
            "roles/svc-ai-freellmapi/templates/env.j2"
        )

    def render(self, config):
        return self.template.render(
            HOST_TIMEZONE="UTC",
            DEPLOYMENT_MODE="compose",
            FREELLMAPI_PORT=3001,
            FREELLMAPI_ENCRYPTION_KEY="a" * 64,
            FREELLMAPI_STARTUP_CONFIG=config,
        )

    def test_interactive_setup_does_not_override_persisted_configuration(self):
        rendered = self.render({})
        self.assertNotIn("FREEAPI_CONFIG_JSON=", rendered)
        self.assertIn("NODE_ENV=production", rendered)
        self.assertIn("PORT=3001", rendered)
        encryption = next(
            line for line in rendered.splitlines() if line.startswith("ENCRYPTION_KEY=")
        )
        self.assertEqual(json.loads(encryption.split("=", 1)[1]), "a" * 64)

    def test_declarative_config_keeps_credentials_in_one_dotenv_assignment(self):
        config = {
            "keys": [{"platform": "openrouter", "key": 'test$secret"\\\nvalue'}],
            "routing": {"strategy": "balanced"},
        }
        rendered = self.render(config)
        assignments = [
            line
            for line in rendered.splitlines()
            if line.startswith("FREEAPI_CONFIG_JSON=")
        ]
        self.assertEqual(len(assignments), 1)
        encoded = assignments[0].split("=", 1)[1]
        value = json.loads(encoded).replace("$$", "$")
        self.assertEqual(json.loads(value), config)

    def test_a_missing_encryption_key_fails_the_render(self):
        with self.assertRaises(jinja2.UndefinedError):
            self.template.render(
                HOST_TIMEZONE="UTC",
                DEPLOYMENT_MODE="compose",
                FREELLMAPI_PORT=3001,
                FREELLMAPI_STARTUP_CONFIG={},
            )
