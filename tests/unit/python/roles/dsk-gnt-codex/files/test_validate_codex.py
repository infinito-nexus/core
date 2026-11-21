import functools
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.annotations.message import in_github_actions

from . import PROJECT_ROOT

SOURCE = PROJECT_ROOT / "roles/dsk-gnt-codex/files/python"
SPEC = importlib.util.spec_from_file_location(
    "validate_codex", SOURCE / "validate_codex.py"
)
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def needs_codex(test):
    """Skip a test without the Codex CLI on PATH, but fail it in GitHub Actions.

    Args:
        test: test method that drives the real client.
    """

    @functools.wraps(test)
    def guarded(self):
        if shutil.which("codex") is None:
            if in_github_actions():
                self.fail(
                    "needs the Codex CLI, which `make install-codex` puts on PATH "
                    "before `make test` in CI"
                )
            self.skipTest("needs the Codex CLI")
        return test(self)

    return guarded


class NeedsCodexTests(unittest.TestCase):
    def _run(self, codex, actions):
        ran = []

        class Probe(unittest.TestCase):
            @needs_codex
            def test_probe(self):
                ran.append(True)

        result = unittest.TestResult()
        with (
            patch.object(shutil, "which", return_value=codex),
            patch.dict(os.environ),
        ):
            os.environ.pop("GITHUB_ACTIONS", None)
            if actions:
                os.environ["GITHUB_ACTIONS"] = actions
            Probe("test_probe").run(result)
        return result, ran

    def test_a_missing_client_fails_in_github_actions(self):
        result, ran = self._run(None, "true")
        self.assertEqual((len(result.failures), len(result.skipped), ran), (1, 0, []))

    def test_a_missing_client_skips_outside_github_actions(self):
        result, ran = self._run(None, "")
        self.assertEqual((len(result.failures), len(result.skipped), ran), (0, 1, []))

    def test_a_present_client_runs_in_github_actions(self):
        result, ran = self._run("/usr/bin/codex", "true")
        self.assertEqual(
            (result.wasSuccessful(), len(result.skipped), ran), (True, 0, [True])
        )


class ValidationTests(unittest.TestCase):
    @needs_codex
    def test_native_rejects_legacy_chat_protocol(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            home = Path(directory)
            config = home / ".codex/config.toml"
            config.parent.mkdir()
            config.write_text(
                'model_provider="infinito"\n[model_providers.infinito]\nname="fixture"\nbase_url="http://localhost/v1"\nwire_api="chat"\n'
            )
            environment = dict(
                os.environ, HOME=directory, CODEX_HOME=str(config.parent)
            )
            result = subprocess.run(
                [
                    shutil.which("codex"),
                    "--strict-config",
                    "app-server",
                    "--print-startup-config",
                ],
                cwd=home,
                env=environment,
                capture_output=True,
                check=False,
                timeout=20,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"startup configuration unavailable", result.stderr)

    @needs_codex
    def test_real_cli_accepts_both_modes_and_uses_helper(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            home = Path(directory)
            program = home / "bin/codex-mode"
            program.parent.mkdir()
            shutil.copyfile(SOURCE / "codex_mode.py", program)
            program.chmod(0o755)
            for extension in Path.home().glob(".vscode*/extensions/openai.chatgpt-*"):
                for binary in extension.glob("bin/linux-*/codex"):
                    link = (
                        home
                        / ".vscode-oss/extensions"
                        / extension.name
                        / "bin"
                        / binary.parent.name
                        / "codex"
                    )
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(binary)
            payload = {
                "gateway_url": "http://127.0.0.1:18081/v1",
                "gateway_key": "fixture-only-key",
                "model": "lmstudio/qwen3-coder",
                "initial_mode": "gateway",
                "reasoning_effort": "medium",
                "subscription_model": "",
                "context_tokens": 32768,
                "auto_compact_tokens": 24576,
                "editor_data_dir": "",
                "helper_path": str(program),
                "credential_timeout_ms": 5000,
                "validation_output_tokens": 512,
            }
            state = home / ".config/infinito/codex.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"mode": "abo", "payload": payload}))
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"object":"response","output":[{"type":"message","content":[{"type":"output_text","text":"OK"}]}]}'
            with patch.object(
                validator.urllib.request, "urlopen", return_value=response
            ) as request:
                validator.validate(program, home, 20)
            body = json.loads(request.call_args.args[0].data)
            self.assertEqual(body["model"], payload["model"])
            self.assertEqual(body["reasoning"], {"effort": "medium"})
            self.assertEqual(
                request.call_args.args[0].full_url,
                payload["gateway_url"] + "/responses",
            )
            self.assertEqual(
                json.loads(state.read_text())["mode"],  # nocheck: cache-read
                "abo",
            )
            response.__enter__.return_value.read.return_value = (
                b'{"object":"response","output":[]}'
            )
            with (
                patch.object(
                    validator.urllib.request, "urlopen", return_value=response
                ),
                self.assertRaises(ValueError),
            ):
                validator.validate(program, home, 20)

    def test_rejected_native_config_fails_before_request(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            home = Path(directory)
            manager_spec = importlib.util.spec_from_file_location(
                "manager_fixture", SOURCE / "codex_mode.py"
            )
            manager = importlib.util.module_from_spec(manager_spec)
            manager_spec.loader.exec_module(manager)
            payload = {
                "gateway_url": "http://localhost/v1",
                "gateway_key": "fixture",
                "model": "local",
                "initial_mode": "gateway",
                "reasoning_effort": "medium",
                "subscription_model": "",
                "context_tokens": 0,
                "auto_compact_tokens": 0,
                "editor_data_dir": "",
                "helper_path": str(SOURCE / "codex_mode.py"),
                "credential_timeout_ms": 5000,
            }
            manager.configure(home, payload)
            with (
                patch.object(
                    validator.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 1),
                ),
                patch.object(validator.urllib.request, "urlopen") as request,
            ):
                with self.assertRaises(ValueError):
                    validator.validate(SOURCE / "codex_mode.py", home, 20)
                request.assert_not_called()
