import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


class UnifiedClaudeCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = os.environ["CLAUDE_MODE_PROGRAM"]
        loader = importlib.machinery.SourceFileLoader("managed_claude", cls.program)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.manager = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.manager)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="claude-cli-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.directory = self.home / ".config/Code - OSS"
        self.config = self.home / ".config/infinito/claude.json"
        self.payload = {
            "gateway_url": "http://127.0.0.1:18081",
            "gateway_key": "test-only-gateway-key",
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
                "retire_profiles": ["Claude Lokal", "Claude Abo"],
                "settings": {},
            },
        }
        self.manager.configure_unified(self.home, self.directory, self.payload)
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if key not in self.manager.MANAGED_ENVIRONMENT
        }
        self.environment.update(
            HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / ".claude")
        )

    def switch(self, mode):
        return subprocess.run(
            [os.environ["TEST_PYTHON"], self.program, mode],
            env=self.environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )

    def test_native_claude_switches_authentication_without_real_credentials(self):
        for mode, logged_in in (("gateway", True), ("abo", False), ("gateway", True)):
            with self.subTest(mode=mode):
                self.assertEqual(self.switch(mode).returncode, 0)
                result = subprocess.run(
                    [os.environ["CLAUDE_BINARY"], "auth", "status"],
                    env=self.environment,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=30,
                )
                data = json.loads(result.stdout)
                self.assertIs(data["loggedIn"], logged_in)
                self.assertEqual(self.switch("status").stdout.strip(), mode)

    def test_native_code_recognizes_the_single_profile(self):
        result = self.code_profile(self.directory, "Claude", ["--list-extensions"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_claude_uses_32k_context_without_a_provider_request(self):
        result = subprocess.run(
            [
                os.environ["CLAUDE_BINARY"],
                "-p",
                "/context",
                "--output-format",
                "json",
                "--setting-sources",
                "user",
                "--tools",
                "",
            ],
            cwd=self.home,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["duration_api_ms"], 0)
        self.assertIn("lmstudio/qwen3-coder", data["result"])
        self.assertIn("32.8k", data["result"])
        self.assertNotIn("1m]", data["result"].lower())

    def test_deployed_profile_contains_every_enabled_agent_extension(self):
        config = json.loads(Path(os.environ["TEST_CONFIG_PATH"]).read_text())
        arguments = [os.environ["CODE_BINARY"]]
        if os.geteuid() == 0:
            arguments.append("--no-sandbox")
        result = subprocess.run(
            [
                *arguments,
                "--user-data-dir",
                config["user_data_dir"],
                "--profile",
                config["payload"]["unified"]["name"],
                "--list-extensions",
            ],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = set(result.stdout.lower().splitlines())
        self.assertTrue(
            set(config["payload"]["extensions"]) <= installed,
            "A configured agent extension is missing from the Claude profile",
        )

    def test_native_claude_picker_shows_configured_labels_and_no_million_token_default(
        self,
    ):
        result = subprocess.run(
            [
                os.environ["CLAUDE_BINARY"],
                "-p",
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--verbose",
                "--setting-sources",
                "user",
                "--tools",
                "",
            ],
            input=json.dumps(
                {
                    "type": "control_request",
                    "request_id": "picker-test",
                    "request": {"subtype": "initialize"},
                }
            )
            + "\n",
            cwd=self.home,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        messages = [json.loads(line) for line in result.stdout.splitlines() if line]
        response = next(
            item["response"] for item in messages if item["type"] == "control_response"
        )
        self.assertEqual(response["subtype"], "success")
        models = response["response"]["models"]
        self.assertEqual(
            [item["value"] for item in models],
            [
                "default",
                *[item["model"] for item in self.payload["unified"]["gateway_models"]],
            ],
        )
        self.assertEqual(models[0]["resolvedModel"], "lmstudio/qwen3-coder")
        self.assertNotIn("[1m]", models[0]["description"])
        self.assertEqual(
            [item["displayName"] for item in models[1:]],
            [item["label"] for item in self.payload["unified"]["gateway_models"]],
        )

    def code_profile(self, directory, name, operation):
        arguments = [os.environ["CODE_BINARY"]]
        if os.geteuid() == 0:
            arguments.append("--no-sandbox")
        return subprocess.run(
            [
                *arguments,
                "--user-data-dir",
                str(directory),
                "--extensions-dir",
                str(self.home / "extensions"),
                "--profile",
                name,
                *operation,
            ],
            env=self.environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )

    def test_native_code_rejects_an_unregistered_profile(self):
        result = self.code_profile(
            self.directory, "Unregistered regression control", ["--list-extensions"]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr)

    def test_native_code_recognizes_the_deployed_profile(self):
        config = json.loads(Path(os.environ["TEST_CONFIG_PATH"]).read_text())
        result = self.code_profile(
            Path(config["user_data_dir"]),
            config["payload"]["unified"]["name"],
            ["--list-extensions"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_code_installs_an_offline_extension_into_the_profile(self):
        archive = self.home / "regression.vsix"
        manifest = {
            "name": "claude-profile-regression",
            "publisher": "infinito-tests",
            "version": "0.0.1",
            "engines": {"vscode": "^1.80.0"},
        }
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("extension/package.json", json.dumps(manifest))
            package.writestr(
                "extension.vsixmanifest",
                '<PackageManifest Version="2.0.0" '
                'xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">'
                '<Metadata><Identity Id="claude-profile-regression" '
                'Version="0.0.1" Publisher="infinito-tests"/>'
                "<DisplayName>CLI regression</DisplayName>"
                "<Description>Offline profile regression fixture</Description>"
                "</Metadata><Installation/><Dependencies/><Assets>"
                '<Asset Type="Microsoft.VisualStudio.Code.Manifest" '
                'Path="extension/package.json" Addressable="true"/>'
                "</Assets></PackageManifest>",
            )
        result = self.code_profile(
            self.directory, "Claude", ["--install-extension", str(archive), "--force"]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.code_profile(self.directory, "Claude", ["--list-extensions"])
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertIn("infinito-tests.claude-profile-regression", installed.stdout)

    def test_open_code_blocks_the_cli_switch_and_keeps_the_state(self):
        before = self.config.read_bytes()
        (self.directory / "SingletonLock").symlink_to("fixture-1234")
        self.assertNotEqual(self.switch("abo").returncode, 0)
        self.assertEqual(self.config.read_bytes(), before)

    def test_cli_changes_are_idempotent_and_theme_detection_survives(self):
        self.assertEqual(self.switch("abo").returncode, 0)
        first = self.config.read_bytes()
        self.assertEqual(self.switch("abo").returncode, 0)
        self.assertEqual(self.config.read_bytes(), first)
        settings = json.loads((self.directory / "User/settings.json").read_text())
        self.assertTrue(settings["window.autoDetectColorScheme"])

    def test_deployed_files_match_the_inventory_payload(self):
        config_path = Path(os.environ["TEST_CONFIG_PATH"])
        config = json.loads(config_path.read_text())
        directory = Path(config["user_data_dir"])
        payload = config["payload"]
        name = payload["unified"]["name"]
        entries = json.loads(
            (directory / "User/globalStorage/storage.json").read_text()
        )["userDataProfiles"]
        selected = [entry for entry in entries if entry["name"] == name]
        self.assertEqual(len(selected), 1)
        retired = set(payload["unified"]["retire_profiles"])
        self.assertFalse(any(entry["name"] in retired for entry in entries))
        editor = json.loads(
            (
                directory / "User/profiles" / selected[0]["location"] / "settings.json"
            ).read_text()
        )
        global_editor = json.loads((directory / "User/settings.json").read_text())
        for key, value in payload["code_settings"].items():
            self.assertTrue(
                editor[key] == value, "Profile differs from deployed editor settings"
            )
            self.assertTrue(
                global_editor[key] == value,
                "Default profile differs from deployed editor settings",
            )
        environment = {
            item["name"]: item["value"]
            for item in editor["claudeCode.environmentVariables"]
        }
        # nocheck: project-root-import climbs from ~/.config/infinito to the tested user's home, not to a project root
        cli_settings = config_path.parents[2] / ".claude/settings.json"
        cli = json.loads(cli_settings.read_text())
        self.assertTrue(
            cli["env"] == environment, "CLI and editor connection environments differ"
        )
        if config["mode"] == "gateway":
            self.assertEqual(
                cli["modelPicker"],
                {
                    "options": payload["unified"]["gateway_models"],
                    "replaceBuiltInOptions": True,
                },
            )
            self.assertEqual(
                environment["ANTHROPIC_DEFAULT_MODEL"], payload["unified"]["model"]
            )
            self.assertEqual(
                environment["CLAUDE_CODE_MAX_OUTPUT_TOKENS"],
                str(payload["unified"]["max_output_tokens"]),
            )
            self.assertTrue(
                environment["ANTHROPIC_AUTH_TOKEN"] == payload["gateway_key"],
                "Gateway credential was not deployed",
            )
            self.assertEqual(
                environment["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"], "1"
            )
        else:
            self.assertNotIn("modelPicker", cli)
            self.assertTrue(
                all(value == "" for value in environment.values()),
                "Subscription mode retained provider overrides",
            )
        self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
