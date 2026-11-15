from __future__ import annotations

import base64
import importlib.util
import json
import re
import unittest
from unittest import mock

from cli.administration.inventory.credentials import schema
from utils.cache.files import read_text
from utils.manager.value_generator import ValueGenerator

from . import PROJECT_ROOT

PLUGIN = (
    PROJECT_ROOT
    / "roles"
    / "web-app-semaphore"
    / "filter_plugins"
    / "semaphore_fixture.py"
)
FIXTURE_JS = (
    PROJECT_ROOT
    / "roles"
    / "web-app-semaphore"
    / "files"
    / "playwright"
    / "workspace-fixture.js"
)
ROLES = ["web-svc-html", "web-app-keycloak"]
SENTINEL = "Sentinel-Value-must-not-render-4711"
ENTRY_KEYS = {"application", "key", "path", "field", "algorithm", "default_b64"}
USER_KEYS = {"name", "path", "field", "algorithm", "validation"}
UNGENERATED = {schema.PLAIN, schema.DEFAULT}
GENERATORS_BLOCK = re.compile(
    r"^const GENERATORS = \{\n(?P<body>.*?)^\};$", re.MULTILINE | re.DOTALL
)
GENERATOR_KEY = re.compile(r"^  (?P<kind>[a-z0-9_]+): ", re.MULTILINE)


def _load():
    spec = importlib.util.spec_from_file_location("semaphore_fixture", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _js_kinds():
    """Returns:
    The kinds ``GENERATORS`` of ``workspace-fixture.js`` generates.
    """
    block = GENERATORS_BLOCK.search(read_text(str(FIXTURE_JS)))
    if block is None:
        raise AssertionError("workspace-fixture.js holds no GENERATORS block")
    return set(GENERATOR_KEY.findall(block["body"]))


class CredentialSchemaRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = _load()
        cls.produced = []
        original = ValueGenerator.generate_value

        def recording(generator, algorithm):
            value = original(generator, algorithm)
            cls.produced.append(value)
            return value

        schema._kind.cache_clear()
        with (
            mock.patch.object(ValueGenerator, "generate_value", recording),
            mock.patch(
                "cli.administration.inventory.provision.passwords.generate_user_password",
                return_value=SENTINEL,
            ),
        ):
            cls.rendered = cls.plugin.semaphore_fixture_credential_schemas(ROLES)
        schema._kind.cache_clear()
        cls.text = json.dumps(cls.rendered)

    def test_no_value_and_no_template_text_render(self):
        self.assertEqual(sorted(self.rendered), sorted(ROLES))
        self.assertNotIn(SENTINEL, self.text)
        self.assertNotIn("{{", self.text)
        values = [value for value in self.produced if value != schema.UNDEFINED]
        self.assertTrue(values)
        for value in values:
            self.assertNotIn(value, self.text)

    def test_entries_name_path_field_and_kind_only(self):
        for role, rendered in self.rendered.items():
            with self.subTest(role):
                self.assertTrue(rendered["credentials"])
                for entry in rendered["credentials"]:
                    self.assertLessEqual(set(entry), ENTRY_KEYS, entry["path"])
                    self.assertEqual(
                        entry["path"],
                        f"{entry['application']}/{entry['key'].replace('.', '/')}",
                    )
                    self.assertEqual(entry["field"], "value")
                for user in rendered["users"]:
                    self.assertEqual(set(user), USER_KEYS, user["name"])
                    self.assertEqual(user["path"], f"users/{user['name']}/password")

    def test_the_keycloak_deploy_pins_the_platform_administrator(self):
        names = {user["name"] for user in self.rendered["web-app-keycloak"]["users"]}
        self.assertIn("platform_administrator", names)

    def kinds(self):
        """Returns:
        Every generator kind the render names.
        """
        return {
            entry["algorithm"]
            for rendered in self.rendered.values()
            for entry in rendered["credentials"] + rendered["users"]
            if entry["algorithm"]
        }

    def test_every_rendered_kind_has_a_generator_in_the_spec(self):
        self.assertEqual(sorted(self.kinds() - UNGENERATED - _js_kinds()), [])

    def test_a_template_default_travels_base64(self):
        default = "{{ lookup('api', 'openai.api_key') }}"
        entry = {"application": "a", "key": "k", "path": "a/k", "field": "value"}
        planted = {
            "credentials": [{**entry, "algorithm": "default", "default": default}],
            "users": [],
        }
        with mock.patch.object(self.plugin, "credential_schema", return_value=planted):
            rendered = self.plugin.semaphore_fixture_credential_schemas(["a"])
        (only,) = rendered["a"]["credentials"]
        self.assertNotIn("{{", json.dumps(rendered))
        self.assertEqual(base64.b64decode(only["default_b64"]).decode(), default)

    def test_negative_control_a_generated_value_is_refused_not_rendered(self):
        with (
            mock.patch.object(
                schema.AlgorithmRecorder, "generate_value", return_value=SENTINEL
            ),
            self.assertRaises(ValueError) as caught,
        ):
            self.plugin.semaphore_fixture_credential_schemas(["web-app-keycloak"])
        self.assertNotIn(SENTINEL, str(caught.exception))

    def test_negative_control_a_kind_missing_from_the_spec_is_caught(self):
        missing = self.kinds() - UNGENERATED - (_js_kinds() - {"alphanumeric"})
        self.assertEqual(sorted(missing), ["alphanumeric"])


if __name__ == "__main__":
    unittest.main()
