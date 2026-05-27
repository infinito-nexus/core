"""Unit tests for ``cli.administration.inventory.credentials.emit``."""

from __future__ import annotations

import unittest
import unittest.mock

from ruamel.yaml.comments import CommentedMap

from cli.administration.inventory.credentials.emit import (
    emit_credentials,
    ensure_map,
)
from utils.handler.vault import VaultHandler


class TestEnsureMap(unittest.TestCase):
    def test_creates_missing_key(self):
        node = CommentedMap()
        sub = ensure_map(node, "k")
        self.assertIs(node["k"], sub)
        self.assertIsInstance(sub, CommentedMap)

    def test_reuses_existing_commented_map(self):
        node = CommentedMap()
        existing = CommentedMap({"a": 1})
        node["k"] = existing
        self.assertIs(ensure_map(node, "k"), existing)

    def test_replaces_non_commented_map_placeholder(self):
        node = CommentedMap()
        node["k"] = "stringified-corrupted-blob"
        sub = ensure_map(node, "k")
        self.assertIsInstance(sub, CommentedMap)
        self.assertEqual(len(sub), 0)


class TestEmitCredentials(unittest.TestCase):
    def setUp(self):
        self.vault = VaultHandler("dummy_pw_file")
        # Stub ansible-vault — return a marker string the test can detect.
        patcher = unittest.mock.patch.object(
            self.vault,
            "encrypt_string",
            side_effect=lambda value, label: (
                f"!vault |\n  $ANSIBLE_VAULT;1.1;AES256\n    ENC[{label}]={value}"
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_flat_scalar_leaf_is_vault_encrypted(self):
        schema = {"api_key": "raw"}
        dest = CommentedMap()
        emit_credentials(
            schema,
            dest,
            app_id="app",
            primary_app_id="app",
            key_path="",
            overrides={},
            vault_handler=self.vault,
            skip_existing=False,
            track_added=None,
        )
        self.assertIn("api_key", dest)
        self.assertIn("ENC[api_key]=raw", str(dest["api_key"]))

    def test_nested_dict_recurses_into_commented_map(self):
        schema = {
            "recaptcha": {
                "key": "{{ K }}",
                "secret": "{{ S }}",
            }
        }
        dest = CommentedMap()
        emit_credentials(
            schema,
            dest,
            app_id="app",
            primary_app_id="app",
            key_path="",
            overrides={},
            vault_handler=self.vault,
            skip_existing=False,
            track_added=None,
        )
        self.assertIsInstance(dest["recaptcha"], CommentedMap)
        self.assertIn("key", dest["recaptcha"])
        self.assertIn("secret", dest["recaptcha"])
        self.assertIn("ENC[key]={{ K }}", str(dest["recaptcha"]["key"]))
        self.assertIn("ENC[secret]={{ S }}", str(dest["recaptcha"]["secret"]))

    def test_none_leaf_becomes_empty_string(self):
        schema = {"missing": None}
        dest = CommentedMap()
        emit_credentials(
            schema,
            dest,
            app_id="app",
            primary_app_id="app",
            key_path="",
            overrides={},
            vault_handler=self.vault,
            skip_existing=False,
            track_added=None,
        )
        self.assertEqual(dest["missing"], "")

    def test_skip_existing_keeps_pre_populated_leaf(self):
        schema = {"api_key": "fresh"}
        dest = CommentedMap()
        dest["api_key"] = "preserved"
        emit_credentials(
            schema,
            dest,
            app_id="app",
            primary_app_id="app",
            key_path="",
            overrides={},
            vault_handler=self.vault,
            skip_existing=True,
            track_added=None,
        )
        self.assertEqual(dest["api_key"], "preserved")

    def test_override_wins_over_default(self):
        schema = {"api_key": "default"}
        dest = CommentedMap()
        emit_credentials(
            schema,
            dest,
            app_id="app",
            primary_app_id="app",
            key_path="",
            overrides={"applications.app.credentials.api_key": "from-override"},
            vault_handler=self.vault,
            skip_existing=False,
            track_added=None,
        )
        self.assertIn("ENC[api_key]=from-override", str(dest["api_key"]))

    def test_track_added_captures_dotted_paths(self):
        schema = {
            "flat": "x",
            "recaptcha": {"key": "k", "secret": "s"},
        }
        dest = CommentedMap()
        added: set[str] = set()
        emit_credentials(
            schema,
            dest,
            app_id="app",
            primary_app_id="app",
            key_path="",
            overrides={},
            vault_handler=self.vault,
            skip_existing=False,
            track_added=added,
        )
        self.assertEqual(
            added,
            {"flat", "recaptcha.key", "recaptcha.secret"},
        )

    def test_nested_dict_with_existing_corrupted_string_is_replaced(self):
        """When prior bake corrupted credentials.recaptcha into a string
        blob, the recursive walker overwrites it with the correct nested
        CommentedMap instead of skipping or appending."""
        schema = {"recaptcha": {"key": "k", "secret": "s"}}
        dest = CommentedMap()
        dest["recaptcha"] = "{'key': '...', 'secret': '...'}"
        emit_credentials(
            schema,
            dest,
            app_id="app",
            primary_app_id="app",
            key_path="",
            overrides={},
            vault_handler=self.vault,
            skip_existing=True,
            track_added=None,
        )
        self.assertIsInstance(dest["recaptcha"], CommentedMap)
        self.assertIn("key", dest["recaptcha"])
        self.assertIn("secret", dest["recaptcha"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
