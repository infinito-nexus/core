import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.plugins.filter.mathstuff import FilterModule as MathFilters
from jinja2.nativetypes import NativeEnvironment

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

SPEC = importlib.util.spec_from_file_location(
    "claude_profiles", PROJECT_ROOT / "roles/dsk-code/files/python/claude_profiles.py"
)
profiles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profiles)


class ClaudeProfilesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "Code - OSS"
        self.storage = self.directory / "User/globalStorage/storage.json"
        self.payload = {
            "gateway_url": "http://127.0.0.1:18081",
            "gateway_key": "test-gateway-key",
            "code_settings": {},
            "profiles": [
                {
                    "name": "Local",
                    "mode": "gateway",
                    "model": "lmstudio/qwen3-coder",
                    "context_tokens": 32768,
                },
                {
                    "name": "Cloud",
                    "mode": "gateway",
                    "model": "openrouter/auto",
                    "context_tokens": None,
                },
                {
                    "name": "Subscription",
                    "mode": "subscription",
                    "model": None,
                    "context_tokens": None,
                },
            ],
        }

    def settings_path(self, name):
        entries = json.loads(self.storage.read_text())[  # nocheck: cache-read
            "userDataProfiles"
        ]
        entry = next(entry for entry in entries if entry["name"] == name)
        return self.directory / "User/profiles" / entry["location"] / "settings.json"

    def test_second_deploy_does_not_change_profile_ids_or_settings(self):
        self.assertTrue(profiles.configure(self.directory, self.payload))
        original = self.storage.read_bytes()  # nocheck: cache-read
        self.assertFalse(profiles.configure(self.directory, self.payload))
        self.assertEqual(original, self.storage.read_bytes())  # nocheck: cache-read

    def test_local_family_and_subagent_requests_use_the_local_model(self):
        settings = profiles.profile_settings(
            self.payload["profiles"][0],
            self.payload["gateway_url"],
            self.payload["gateway_key"],
        )
        env = {
            item["name"]: item["value"]
            for item in settings["claudeCode.environmentVariables"]
        }
        for key in (
            "ANTHROPIC_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL",
        ):
            self.assertEqual(env[key], "lmstudio/qwen3-coder")
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "32768")

    def test_cloud_profile_has_no_local_context_limit(self):
        settings = profiles.profile_settings(
            self.payload["profiles"][1],
            self.payload["gateway_url"],
            self.payload["gateway_key"],
        )
        env = {
            item["name"]: item["value"]
            for item in settings["claudeCode.environmentVariables"]
        }
        self.assertEqual(env["ANTHROPIC_MODEL"], "openrouter/auto")
        self.assertNotIn("CLAUDE_CODE_MAX_CONTEXT_TOKENS", env)

    def test_subscription_profile_removes_copied_gateway_credentials(self):
        profiles.configure(self.directory, self.payload)
        path = self.settings_path("Subscription")
        path.write_text(
            json.dumps(
                {
                    "editor.fontSize": 17,
                    "claudeCode.environmentVariables": [
                        {"name": "ANTHROPIC_AUTH_TOKEN", "value": "old-test-key"}
                    ],
                }
            )
        )
        profiles.configure(self.directory, self.payload)
        settings = json.loads(path.read_text())  # nocheck: cache-read
        self.assertEqual(settings["claudeCode.environmentVariables"], [])
        self.assertFalse(settings["claudeCode.disableLoginPrompt"])
        self.assertEqual(settings["editor.fontSize"], 17)

    def test_other_profiles_and_global_settings_are_preserved(self):
        self.storage.parent.mkdir(parents=True)
        other = {"name": "Existing", "location": "existing"}
        self.storage.write_text(
            json.dumps({"userDataProfiles": [other], "other-state": "keep"})
        )
        default = self.directory / "User/settings.json"
        default.write_text('{"editor.fontSize": 19}')
        profiles.configure(self.directory, self.payload)
        storage = json.loads(self.storage.read_text())  # nocheck: cache-read
        self.assertIn(other, storage["userDataProfiles"])
        self.assertEqual(storage["other-state"], "keep")
        self.assertEqual(
            default.read_text(),  # nocheck: cache-read
            '{"editor.fontSize": 19}',
        )

    def test_every_named_profile_receives_the_editor_settings(self):
        self.payload["code_settings"] = {
            "search.ripgrep.maxThreads": 4,
            "files.watcherExclude": {"**/.worktrees/**": True},
        }
        profiles.configure(self.directory, self.payload)
        path = self.settings_path("Local")
        path.write_text(
            json.dumps(
                {
                    "editor.fontSize": 17,
                    "files.watcherExclude": {"**/node_modules/**": True},
                }
            )
        )
        profiles.configure(self.directory, self.payload)
        for name in ("Local", "Cloud", "Subscription"):
            with self.subTest(profile=name):
                settings = json.loads(
                    self.settings_path(name).read_text()  # nocheck: cache-read
                )
                self.assertEqual(settings["search.ripgrep.maxThreads"], 4)
                self.assertTrue(settings["files.watcherExclude"]["**/.worktrees/**"])
        settings = json.loads(path.read_text())  # nocheck: cache-read
        self.assertEqual(settings["editor.fontSize"], 17)
        self.assertTrue(settings["files.watcherExclude"]["**/node_modules/**"])

    def test_unrelated_environment_variables_are_preserved(self):
        profiles.configure(self.directory, self.payload)
        path = self.settings_path("Local")
        extra = {"name": "NODE_EXTRA_CA_CERTS", "value": "/local/ca.crt"}
        path.write_text(json.dumps({"claudeCode.environmentVariables": [extra]}))
        profiles.configure(self.directory, self.payload)
        self.assertIn(
            extra,
            json.loads(path.read_text())[  # nocheck: cache-read
                "claudeCode.environmentVariables"
            ],
        )

    def test_jsonc_settings_preserve_strings_and_unrelated_values(self):
        path = Path(self.temporary.name) / "settings.json"
        path.write_text(
            '{"url":"http://example.test/a/*b*/", // comment\n "text":"comma,}", "list":[1,],}'
        )
        self.assertEqual(
            profiles.read_settings(path),
            {"url": "http://example.test/a/*b*/", "text": "comma,}", "list": [1]},
        )

    def test_managed_credentials_are_owner_readable_only(self):
        profiles.configure(self.directory, self.payload)
        self.assertEqual(self.settings_path("Local").stat().st_mode & 0o777, 0o600)

    def test_rotation_updates_key_without_creating_another_profile(self):
        profiles.configure(self.directory, self.payload)
        path = self.settings_path("Local")
        self.payload["gateway_key"] = "rotated-test-gateway-key"
        self.assertTrue(profiles.configure(self.directory, self.payload))
        self.assertEqual(path, self.settings_path("Local"))
        env = {
            item["name"]: item["value"]
            for item in json.loads(path.read_text())[  # nocheck: cache-read
                "claudeCode.environmentVariables"
            ]
        }
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "rotated-test-gateway-key")

    def test_open_editor_is_refused_before_any_settings_write(self):
        self.directory.mkdir()
        (self.directory / "SingletonLock").symlink_to("host-1234")
        with self.assertRaisesRegex(ValueError, "Close Code"):
            profiles.configure(self.directory, self.payload)
        self.assertFalse(self.storage.exists())

    def test_invalid_profile_does_not_partially_register_profiles(self):
        self.payload["profiles"][1]["mode"] = "invalid"
        with self.assertRaisesRegex(ValueError, "mode"):
            profiles.configure(self.directory, self.payload)
        self.assertFalse(self.storage.exists())
        self.assertFalse((self.directory / "User/profiles").exists())

    def test_existing_profile_cannot_escape_the_profiles_directory(self):
        self.storage.parent.mkdir(parents=True)
        self.storage.write_text(
            json.dumps(
                {"userDataProfiles": [{"name": "Local", "location": "../../outside"}]}
            )
        )
        with self.assertRaisesRegex(ValueError, "relative profile"):
            profiles.configure(self.directory, self.payload)

    def test_gateway_profile_requires_a_credential(self):
        self.payload["gateway_key"] = ""
        with self.assertRaisesRegex(ValueError, "gateway_key"):
            profiles.configure(self.directory, self.payload)
        self.assertFalse(self.storage.exists())


class UnifiedClaudeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.directory = self.home / ".config/Code - OSS"
        self.storage = self.directory / "User/globalStorage/storage.json"
        self.config = self.home / ".config/infinito/claude.json"
        self.settings = self.home / ".claude/settings.json"
        self.payload = {
            "gateway_url": "http://127.0.0.1:18081",
            "gateway_key": "test-gateway-key",
            "profiles": [],
            "code_settings": {"window.autoDetectColorScheme": True},
            "unified": {
                "name": "Claude",
                "initial_mode": "gateway",
                "subscription_model": "opus",
                "model": "lmstudio/qwen3-coder",
                "background_model": "lmstudio/qwen3-coder",
                "context_tokens": 32768,
                "max_output_tokens": 4096,
                "gateway_models": [
                    {
                        "model": "lmstudio/qwen3-coder",
                        "label": "Qwen3 Coder",
                        "description": "Local 32k",
                    },
                    {
                        "model": "openrouter/free",
                        "label": "OpenRouter Free",
                        "description": "Free routing",
                    },
                ],
                "retire_profiles": ["Claude Lokal", "Claude OpenRouter", "Claude Abo"],
                "settings": {"alwaysThinkingEnabled": False},
            },
        }

    def apply(self, mode=None):
        return profiles.configure_unified(self.home, self.directory, self.payload, mode)

    def profile_path(self):
        entry = json.loads(self.storage.read_text())[  # nocheck: cache-read
            "userDataProfiles"
        ][0]
        return self.directory / "User/profiles" / entry["location"] / "settings.json"

    def test_migration_removes_old_choices_without_creating_backups(self):
        self.storage.parent.mkdir(parents=True)
        self.storage.write_text(
            json.dumps(
                {
                    "userDataProfiles": [
                        {"name": "Claude Lokal", "location": "old-local"}
                    ],
                    "profileAssociations": {
                        "workspaces": {"file:///project": "old-local"}
                    },
                }
            )
        )
        history = self.home / ".claude/projects/history.jsonl"
        history.parent.mkdir(parents=True)
        history.write_text("keep history")
        login = self.home / ".claude/.credentials.json"
        login.write_text("keep login")
        self.apply()
        storage = json.loads(self.storage.read_text())  # nocheck: cache-read
        self.assertEqual([p["name"] for p in storage["userDataProfiles"]], ["Claude"])
        self.assertEqual(
            storage["profileAssociations"]["workspaces"]["file:///project"],
            storage["userDataProfiles"][0]["location"],
        )
        self.assertEqual(history.read_text(), "keep history")  # nocheck: cache-read
        self.assertEqual(login.read_text(), "keep login")  # nocheck: cache-read
        self.assertFalse(list(self.home.rglob("*.bak")))  # nocheck: project-walk

    def test_redeploy_is_idempotent_and_preserves_selected_subscription_mode(self):
        self.assertTrue(self.apply())
        identity = self.storage.read_bytes()  # nocheck: cache-read
        self.assertFalse(self.apply())
        self.apply("abo")
        self.assertFalse(self.apply())
        self.assertEqual(
            json.loads(self.config.read_text())["mode"],  # nocheck: cache-read
            "abo",
        )
        self.assertEqual(self.storage.read_bytes(), identity)  # nocheck: cache-read

    def test_mode_switch_updates_cli_and_editor_authentication_together(self):
        self.apply()
        gateway = json.loads(self.settings.read_text())  # nocheck: cache-read
        self.assertEqual(gateway["env"]["ANTHROPIC_AUTH_TOKEN"], "test-gateway-key")
        self.assertEqual(
            gateway["env"]["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"], "1"
        )
        self.apply("abo")
        subscription = json.loads(self.settings.read_text())  # nocheck: cache-read
        self.assertEqual(subscription["model"], "opus")
        self.assertNotIn("modelPicker", subscription)
        self.assertFalse(subscription["apiKeyHelper"])
        self.assertTrue(all(value == "" for value in subscription["env"].values()))
        editor = json.loads(self.profile_path().read_text())  # nocheck: cache-read
        self.assertFalse(editor["claudeCode.disableLoginPrompt"])
        self.assertTrue(
            all(
                item["value"] == ""
                for item in editor["claudeCode.environmentVariables"]
            )
        )
        self.apply("gateway")
        self.assertEqual(
            json.loads(self.settings.read_text())[  # nocheck: cache-read
                "env"
            ]["ANTHROPIC_AUTH_TOKEN"],
            "test-gateway-key",
        )

    def test_gateway_picker_has_explicit_labels_and_finite_local_output_budget(self):
        self.apply()
        settings = json.loads(self.settings.read_text())  # nocheck: cache-read
        self.assertEqual(
            settings["modelPicker"]["options"],
            self.payload["unified"]["gateway_models"],
        )
        self.assertTrue(settings["modelPicker"]["replaceBuiltInOptions"])
        self.assertEqual(settings["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "32768")
        self.assertEqual(settings["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"], "4096")
        for family in ("OPUS", "SONNET", "FABLE"):
            self.assertEqual(
                settings["env"][f"ANTHROPIC_DEFAULT_{family}_MODEL"],
                "lmstudio/qwen3-coder",
            )

    def test_profile_extension_task_installs_claude_and_codex_but_not_disabled_addons(
        self,
    ):
        tasks = load_yaml_any(
            PROJECT_ROOT / "roles/dsk-code/tasks/01_claude_profiles.yml"
        )
        task = next(task for task in tasks if "product(" in task.get("loop", ""))
        renderer = NativeEnvironment()
        renderer.filters.update(CoreFilters().filters())
        renderer.filters.update(MathFilters().filters())
        addons = {
            "claude-code": {
                "enabled": True,
                "mechanism": "extension",
                "config": {
                    "extension_id": "anthropic.claude-code",
                    "unified": {"name": "Claude"},
                    "profiles": [],
                },
            },
            "codex": {
                "enabled": True,
                "mechanism": "extension",
                "config": {"extension_id": "openai.chatgpt"},
            },
            "disabled": {
                "enabled": False,
                "mechanism": "extension",
                "config": {"extension_id": "disabled.fixture"},
            },
        }
        self.assertEqual(
            renderer.from_string(task["loop"]).render(code_addons=addons),
            [("Claude", "anthropic.claude-code"), ("Claude", "openai.chatgpt")],
        )

    def test_gateway_picker_rejects_a_million_token_local_suffix_before_writing(self):
        self.payload["unified"]["gateway_models"][0]["model"] += "[1m]"
        self.payload["unified"]["model"] += "[1m]"
        with self.assertRaisesRegex(ValueError, "no \\[1m\\]"):
            self.apply()
        self.assertFalse(self.settings.exists())

    def test_local_output_budget_cannot_consume_the_whole_context(self):
        self.payload["unified"]["max_output_tokens"] = 32768
        with self.assertRaisesRegex(ValueError, "below context_tokens"):
            self.apply()
        self.assertFalse(self.settings.exists())

    def test_inventory_replaces_manual_settings_and_controls_system_theme_detection(
        self,
    ):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text('{"manual":"discard","apiKeyHelper":"old-helper"}')
        self.apply()
        self.assertNotIn(
            "manual",
            json.loads(self.settings.read_text()),  # nocheck: cache-read
        )
        self.assertEqual(
            json.loads(
                (
                    self.directory / "User/settings.json"
                ).read_text()  # nocheck: cache-read
            ),
            self.payload["code_settings"],
        )
        self.assertTrue(
            json.loads(self.profile_path().read_text())[  # nocheck: cache-read
                "window.autoDetectColorScheme"
            ]
        )

    def test_configuration_and_all_settings_are_private(self):
        self.apply()
        for path in (self.config, self.settings, self.storage, self.profile_path()):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_open_code_refuses_mode_change_without_partial_updates(self):
        self.apply()
        initial = (
            self.config.read_bytes(),  # nocheck: cache-read
            self.settings.read_bytes(),  # nocheck: cache-read
        )
        (self.directory / "SingletonLock").symlink_to("host-1234")
        with self.assertRaisesRegex(ValueError, "Close Code"):
            self.apply("abo")
        self.assertEqual(
            (
                self.config.read_bytes(),  # nocheck: cache-read
                self.settings.read_bytes(),  # nocheck: cache-read
            ),
            initial,
        )

    def test_overriding_owned_auth_settings_is_rejected_before_writes(self):
        self.payload["unified"]["settings"]["env"] = {
            "ANTHROPIC_AUTH_TOKEN": "override"
        }
        with self.assertRaisesRegex(ValueError, "must not override"):
            self.apply()
        self.assertFalse(self.settings.exists())

    def test_switch_command_status_and_mode_changes_use_the_deployed_config(self):
        self.apply()
        with (
            patch.object(Path, "home", return_value=self.home),
            patch.object(profiles.sys, "argv", ["claude-mode", "abo"]),
            patch("builtins.print"),
        ):
            profiles.main()
        self.assertEqual(
            json.loads(self.config.read_text())["mode"],  # nocheck: cache-read
            "abo",
        )


if __name__ == "__main__":
    unittest.main()
