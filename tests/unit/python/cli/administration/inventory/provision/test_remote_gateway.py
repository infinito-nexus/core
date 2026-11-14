from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.provision.remote_gateway import (
    drop_gateway_role,
    named_gateway_host,
)
from cli.administration.inventory.ruamel_io import dump_document


def _naming(gateway: str) -> dict:
    return {
        "applications": {
            "svc-ai-litellm": {"services": {"litellm": {"gateway_host": gateway}}}
        }
    }


class TestNamedGatewayHost(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host_vars = self.root / "galaxyserver.yml"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_fresh_host_names_none(self):
        self.assertEqual(named_gateway_host(self.host_vars, None, None), "")

    def test_the_existing_host_vars_name_it(self):
        dump_document(self.host_vars, _naming("echoserver"))
        self.assertEqual(named_gateway_host(self.host_vars, None, None), "echoserver")

    def test_a_vars_file_names_it_for_a_fresh_inventory(self):
        vars_file = self.root / "vars.yml"
        dump_document(vars_file, _naming("echoserver"))
        self.assertEqual(
            named_gateway_host(self.host_vars, None, vars_file), "echoserver"
        )

    def test_the_vars_json_wins_over_the_file(self):
        dump_document(self.host_vars, _naming("echoserver"))
        self.assertEqual(
            named_gateway_host(self.host_vars, json.dumps(_naming("foxtrot")), None),
            "foxtrot",
        )

    def test_invalid_vars_json_exits_with_the_vars_message(self):
        with self.assertRaises(SystemExit) as raised:
            named_gateway_host(self.host_vars, "{not json", None)
        self.assertIn("Invalid JSON passed to --vars", str(raised.exception.code))
        self.assertIsInstance(raised.exception.__cause__, json.JSONDecodeError)

    def test_valid_vars_json_without_a_gateway_keeps_the_held_one(self):
        dump_document(self.host_vars, _naming("echoserver"))
        self.assertEqual(
            named_gateway_host(self.host_vars, json.dumps({"applications": {}}), None),
            "echoserver",
        )


class TestDropGatewayRole(unittest.TestCase):
    def test_the_gateway_group_is_removed_and_the_rest_kept(self):
        inventory = {
            "all": {
                "children": {
                    "svc-ai-litellm": {"hosts": {"galaxyserver": {}}},
                    "web-app-openwebui": {"hosts": {"galaxyserver": {}}},
                }
            }
        }
        self.assertTrue(drop_gateway_role(inventory))
        self.assertEqual(list(inventory["all"]["children"]), ["web-app-openwebui"])

    def test_an_inventory_without_the_gateway_is_left_alone(self):
        inventory = {"all": {"children": {"web-app-hermes": {"hosts": {}}}}}
        self.assertFalse(drop_gateway_role(inventory))
        self.assertEqual(list(inventory["all"]["children"]), ["web-app-hermes"])


if __name__ == "__main__":
    unittest.main()
