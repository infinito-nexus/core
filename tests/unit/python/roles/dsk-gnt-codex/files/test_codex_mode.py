import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from . import PROJECT_ROOT

SOURCE = PROJECT_ROOT / "roles/dsk-gnt-codex/files/python/codex_mode.py"
SPEC = importlib.util.spec_from_file_location("codex_mode", SOURCE)
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class CodexModeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.payload = {
            "gateway_url": "http://127.0.0.1:18081/v1",
            "gateway_key": "fixture-only-key",
            "model": "lmstudio/qwen3-coder",
            "initial_mode": "gateway",
            "reasoning_effort": "medium",
            "subscription_model": "",
            "context_tokens": 32768,
            "auto_compact_tokens": 24576,
            "editor_data_dir": "",
            "helper_path": str(SOURCE),
            "credential_timeout_ms": 5000,
        }

    def config(self):
        return tomllib.loads(
            (self.home / ".codex/config.toml").read_text()  # nocheck: cache-read
        )

    def test_gateway_uses_responses_and_private_helper(self):
        manager.configure(self.home, self.payload)
        config = self.config()
        provider = config["model_providers"]["infinito"]
        self.assertEqual(provider["wire_api"], "responses")
        self.assertEqual(provider["auth"]["args"], ["credential"])
        self.assertNotIn("env_key", provider)
        self.assertNotIn(
            self.payload["gateway_key"],
            (self.home / ".codex/config.toml").read_text(),  # nocheck: cache-read
        )
        self.assertEqual(config["model_context_window"], 32768)
        self.assertEqual(config["model_reasoning_effort"], "medium")
        for path in (".codex/config.toml", ".config/infinito/codex.json"):
            self.assertEqual((self.home / path).stat().st_mode & 0o777, 0o600)
        self.assertFalse(manager.configure(self.home, self.payload))

    def test_switch_preserves_login_and_unrelated_settings(self):
        folder = self.home / ".codex"
        folder.mkdir()
        (folder / "auth.json").write_text('{"fixture":"saved-login"}')
        (folder / "config.toml").write_text(
            'approval_policy = "on-request"\n[mcp_servers.test]\ncommand = "example"\n'
        )
        manager.configure(self.home, self.payload)
        manager.configure(self.home, self.payload, "abo")
        config = self.config()
        self.assertEqual(config["model_provider"], "openai")
        self.assertEqual(config["forced_login_method"], "chatgpt")
        self.assertNotIn("model", config)
        self.assertNotIn("model_context_window", config)
        self.assertNotIn("model_reasoning_effort", config)
        self.assertNotIn("infinito", config["model_providers"])
        self.assertEqual(config["mcp_servers"]["test"]["command"], "example")
        self.assertEqual(
            (folder / "auth.json").read_text(),  # nocheck: cache-read
            '{"fixture":"saved-login"}',
        )
        self.assertFalse(manager.configure(self.home, self.payload))
        manager.configure(self.home, self.payload, "gateway")
        self.assertEqual(self.config()["model"], self.payload["model"])

    def test_rotation_keeps_selected_mode(self):
        manager.configure(self.home, self.payload, "abo")
        rotated = dict(self.payload, gateway_key="rotated-fixture-key")
        manager.configure(self.home, rotated)
        self.assertEqual(manager.read_state(self.home)["mode"], "abo")
        self.assertEqual(
            manager.read_state(self.home)["payload"]["gateway_key"],
            "rotated-fixture-key",
        )

    def test_editor_lock_refuses_write(self):
        editor = self.home / "editor"
        editor.mkdir()
        (editor / "SingletonLock").symlink_to("missing-lock-owner")
        with self.assertRaises(ValueError):
            manager.configure(
                self.home, dict(self.payload, editor_data_dir=str(editor))
            )
        self.assertFalse((self.home / ".codex/config.toml").exists())

    def test_invalid_compaction_refuses_write(self):
        with self.assertRaises(ValueError):
            manager.configure(
                self.home, dict(self.payload, auto_compact_tokens=1000000)
            )
        self.assertIsNone(manager.read_state(self.home))

    def test_zero_limits_leave_the_window_unmanaged(self):
        manager.configure(
            self.home, dict(self.payload, context_tokens=0, auto_compact_tokens=0)
        )
        config = self.config()
        self.assertNotIn("model_context_window", config)
        self.assertNotIn("model_auto_compact_token_limit", config)

    def test_compaction_without_a_window_refuses_write(self):
        for limits in (
            {"context_tokens": 0, "auto_compact_tokens": 1024},
            {"context_tokens": None, "auto_compact_tokens": 0},
            {"context_tokens": -1, "auto_compact_tokens": 0},
        ):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                manager.configure(self.home, dict(self.payload, **limits))
        self.assertIsNone(manager.read_state(self.home))

    def test_disabled_reasoning_is_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            manager.configure(self.home, dict(self.payload, reasoning_effort="none"))
        self.assertIsNone(manager.read_state(self.home))

    def test_redeploy_replaces_stale_disabled_reasoning(self):
        folder = self.home / ".codex"
        folder.mkdir()
        (folder / "config.toml").write_text('model_reasoning_effort = "none"\n')
        manager.configure(self.home, self.payload)
        self.assertEqual(self.config()["model_reasoning_effort"], "medium")

    def test_legacy_environment_removed(self):
        legacy = self.home / ".config/environment.d/50-infinito-codex.conf"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("INFINITO_GATEWAY_KEY=fixture")
        manager.configure(self.home, self.payload)
        self.assertFalse(legacy.exists())

    def test_cli_alias_and_credential(self):
        manager.configure(self.home, self.payload, "abo")
        environment = dict(
            os.environ, HOME=str(self.home), CODEX_HOME=str(self.home / ".codex")
        )
        with patch.dict(os.environ, environment, clear=True):
            result = subprocess.run(
                [shutil.which("python3"), str(SOURCE), "api"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertNotIn(self.payload["gateway_key"], result.stdout)
            result = subprocess.run(
                [shutil.which("python3"), str(SOURCE), "credential"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(result.stdout.strip(), self.payload["gateway_key"])
        self.assertEqual(
            json.loads(
                (
                    self.home / ".config/infinito/codex.json"
                ).read_text()  # nocheck: cache-read
            )["mode"],
            "gateway",
        )


if __name__ == "__main__":
    unittest.main()
