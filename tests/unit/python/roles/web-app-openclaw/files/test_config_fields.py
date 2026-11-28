from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-openclaw/files/python/config_fields.py"
PATHS = {
    "allowedOrigins": ["gateway", "controlUi", "allowedOrigins"],
    "baseUrl": ["models", "providers", "litellm", "baseUrl"],
}
DOCUMENT = {
    "gateway": {
        "controlUi": {"allowedOrigins": ["https://claw.example.test"]},
        "auth": {"mode": "trusted-proxy"},
    },
    "models": {"providers": {"litellm": {"apiKey": "held-key-value"}}},
}


def _module(script: Path = SCRIPT):
    spec = importlib.util.spec_from_file_location("config_fields", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestConfigFields(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.config = Path(self.directory.name) / "openclaw.json"
        self.module = _module()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_a_held_path_returns_its_value_and_a_missing_one_nothing(self) -> None:
        self.config.write_text(json.dumps(DOCUMENT), encoding="utf-8")
        self.assertEqual(
            {"allowedOrigins": ["https://claw.example.test"]},
            self.module.fields(self.config, PATHS),
        )

    def test_only_the_requested_paths_leave_the_file(self) -> None:
        self.config.write_text(json.dumps(DOCUMENT), encoding="utf-8")
        printed = io.StringIO()
        with (
            mock.patch("sys.argv", ["config_fields.py", str(self.config)]),
            mock.patch("sys.stdin", io.StringIO(json.dumps(PATHS))),
            mock.patch("sys.stdout", printed),
        ):
            self.module.main()
        self.assertNotIn("held-key-value", printed.getvalue())
        self.assertNotIn("trusted-proxy", printed.getvalue())
        self.assertEqual(
            {"allowedOrigins": ["https://claw.example.test"]},
            json.loads(printed.getvalue()),
        )

    def test_a_missing_file_reports_nothing(self) -> None:
        self.assertEqual({}, self.module.fields(self.config, PATHS))

    def test_a_file_that_is_no_json_document_reports_nothing(self) -> None:
        self.config.write_text("{ gateway: { mode: 'local' } // json5", "utf-8")
        self.assertEqual({}, self.module.fields(self.config, PATHS))

    def test_a_path_through_a_scalar_is_missing(self) -> None:
        self.config.write_text(json.dumps({"gateway": "local"}), encoding="utf-8")
        self.assertEqual(
            {}, self.module.fields(self.config, {"mode": ["gateway", "auth", "mode"]})
        )

    def test_a_wildcard_takes_only_the_rest_of_the_path_out_of_each_entry(
        self,
    ) -> None:
        held = {
            "mcp": {
                "servers": {
                    "web-app-gitea": {
                        "url": "http://gitea/mcp",
                        "headers": {"Authorization": "Bearer held-token-value"},
                    },
                    "no-url": {"transport": "sse"},
                }
            }
        }
        self.config.write_text(json.dumps(held), encoding="utf-8")
        found = self.module.fields(
            self.config, {"servers": ["mcp", "servers", "*", "url"]}
        )
        self.assertEqual({"servers": {"web-app-gitea": "http://gitea/mcp"}}, found)
        self.assertNotIn("held-token-value", json.dumps(found))

    def test_a_wildcard_the_file_does_not_reach_holds_no_entries(self) -> None:
        self.config.write_text(json.dumps(DOCUMENT), encoding="utf-8")
        self.assertEqual(
            {"servers": {}},
            self.module.fields(
                self.config, {"servers": ["mcp", "servers", "*", "url"]}
            ),
        )


if __name__ == "__main__":
    unittest.main()
