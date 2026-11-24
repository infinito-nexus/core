from __future__ import annotations

import importlib.util
import json
import unittest
from unittest.mock import patch

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/web-app-openwebui"
SCRIPT_PATH = ROLE / "files/python/agent_model_grants.py"
AGENT_MODELS = {
    "hermes": "/roles/web-app-hermes/agent-user",
    "openclaw": "/roles/web-app-openclaw/agent-user",
}
CHAT_MODEL = "qwen2.5:0.5b"
AUDIO_MODEL = "transcriber"
GATEWAY_FAILED_RC = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))[
    "OPENWEBUI_GATEWAY_FAILED_RC"
]


def load_script(gateway_url="http://litellm:4000"):
    spec = importlib.util.spec_from_file_location("agent_model_grants", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        "os.environ",
        {
            "OPENWEBUI_BASE": "http://localhost:8080",
            "OPENWEBUI_ADMIN_EMAIL": "administrator@example.org",
            "OPENWEBUI_ADMIN_NAME": "administrator",
            "OPENWEBUI_ADMIN_PASSWORD": "x" * 32,
            "OPENWEBUI_GATEWAY_URL": gateway_url,
            "OPENWEBUI_GATEWAY_KEY": "sk-gateway",
            "OPENWEBUI_AGENT_MODELS": json.dumps(AGENT_MODELS),
            "OPENWEBUI_GATEWAY_FAILED_RC": str(GATEWAY_FAILED_RC),
        },
    ):
        spec.loader.exec_module(module)
    return module


class FakeOpenWebUI:
    """
    Args:
        gateway_modes: gateway model id -> the mode its model_info declares.
    """

    def __init__(self, gateway_modes):
        self.gateway_modes = gateway_modes
        self.grants = {}
        self.groups = {}

    def call(self, url, key, payload=None):
        if url.endswith("/v1/models"):
            return 200, {"data": [{"id": model} for model in self.gateway_modes]}
        if url.endswith("/v1/model/info"):
            return 200, {
                "data": [
                    {"model_name": model, "model_info": {"mode": mode}}
                    for model, mode in self.gateway_modes.items()
                ]
            }
        if url.endswith("/api/v1/groups/"):
            return 200, [{"id": gid, "name": name} for name, gid in self.groups.items()]
        if url.endswith("/api/v1/groups/create"):
            self.groups[payload["name"]] = f"g{len(self.groups)}"
            return 200, {"id": self.groups[payload["name"]]}
        if url.endswith("/api/v1/models/model/access/update"):
            self.grants[payload["id"]] = payload["access_grants"]
            return 200, {}
        raise AssertionError(url)

    def stored(self, model_id):
        return sorted(
            (g["principal_type"], g["principal_id"], g["permission"])
            for g in self.grants.get(model_id, [])
        )


def patched(script, fake):
    return patch.multiple(script, call=fake.call, current_grants=fake.stored)


def refusing_call(url, *_rest):
    raise AssertionError(f"unexpected call to {url}")


def unreachable_call(url, *_rest):
    raise ConnectionRefusedError(111, f"refused {url}")


def failing_call(url, *_rest):
    return 401, '{"error": "Received API Key = sk-gateway"}'


class TestGatewayFailure(unittest.TestCase):
    def assert_gateway_failure(self, call):
        script = load_script()
        with patch.multiple(script, call=call, AGENT_MODELS={}):
            with patch("sys.stderr") as stderr:
                with self.assertRaises(SystemExit) as stop:
                    script.provision("key")
        self.assertEqual(stop.exception.code, GATEWAY_FAILED_RC)
        return "".join(str(c.args[0]) for c in stderr.write.call_args_list)

    def test_an_unreachable_gateway_ends_the_run_without_a_retry(self):
        reason = self.assert_gateway_failure(unreachable_call)
        self.assertIn("http://litellm:4000/v1/models is unreachable", reason)

    def test_a_refused_listing_ends_the_run_without_its_body(self):
        reason = self.assert_gateway_failure(failing_call)
        self.assertIn("answered HTTP 401", reason)
        self.assertNotIn("sk-gateway", reason)

    def test_negative_control_an_open_webui_failure_stays_retryable(self):
        script = load_script()
        fake = FakeOpenWebUI({CHAT_MODEL: "chat"})

        def groups_down(url, key, payload=None):
            if url.endswith("/api/v1/groups/"):
                return 502, "bad gateway"
            return fake.call(url, key, payload)

        with patch.multiple(script, call=groups_down, current_grants=fake.stored):
            with self.assertRaises(SystemExit) as stop:
                script.provision("key")
        self.assertNotEqual(stop.exception.code, GATEWAY_FAILED_RC)


class TestProvision(unittest.TestCase):
    def test_gateway_models_become_public_and_agents_stay_in_their_group(self):
        script = load_script()
        fake = FakeOpenWebUI({CHAT_MODEL: "chat", "hermes": "chat"})
        with patched(script, fake):
            self.assertTrue(script.provision("key"))
        self.assertEqual(fake.grants[CHAT_MODEL], script.PUBLIC)
        for model_id, group in AGENT_MODELS.items():
            self.assertEqual(
                fake.grants[model_id],
                [
                    {
                        "principal_type": "group",
                        "principal_id": fake.groups[group],
                        "permission": "read",
                    }
                ],
            )

    def test_a_second_run_changes_nothing(self):
        script = load_script()
        fake = FakeOpenWebUI({CHAT_MODEL: "chat", AUDIO_MODEL: "audio_transcription"})
        with patched(script, fake):
            script.provision("key")
            self.assertFalse(script.provision("key"))

    def test_without_a_gateway_only_the_agents_are_granted(self):
        script = load_script(gateway_url="")
        fake = FakeOpenWebUI({CHAT_MODEL: "chat"})
        with patched(script, fake):
            script.provision("key")
        self.assertEqual(set(fake.grants), set(AGENT_MODELS))

    def test_without_a_gateway_and_a_broker_nothing_is_called(self):
        script = load_script(gateway_url="")
        with patch.multiple(script, call=refusing_call, AGENT_MODELS={}):
            self.assertFalse(script.provision("key"))

    def test_negative_control_with_a_gateway_the_refusing_call_fires(self):
        script = load_script()
        with patch.multiple(script, call=refusing_call, AGENT_MODELS={}):
            with self.assertRaises(AssertionError):
                script.provision("key")


class TestUngrantedModes(unittest.TestCase):
    def test_an_audio_or_embedding_model_is_not_granted_while_a_chat_model_is(self):
        script = load_script()
        for mode in ("audio_transcription", "audio_speech", "embedding"):
            with self.subTest(mode=mode):
                fake = FakeOpenWebUI({CHAT_MODEL: "chat", AUDIO_MODEL: mode})
                with patched(script, fake):
                    script.provision("key")
                self.assertEqual(fake.stored(AUDIO_MODEL), [])
                self.assertEqual(fake.grants[CHAT_MODEL], script.PUBLIC)

    def test_a_model_without_a_declared_mode_stays_public(self):
        script = load_script()
        fake = FakeOpenWebUI({CHAT_MODEL: None})
        with patched(script, fake):
            script.provision("key")
        self.assertEqual(fake.grants[CHAT_MODEL], script.PUBLIC)

    def test_a_public_grant_an_older_run_wrote_on_an_audio_route_is_revoked(self):
        script = load_script()
        fake = FakeOpenWebUI({CHAT_MODEL: "chat", AUDIO_MODEL: "audio_transcription"})
        fake.grants[AUDIO_MODEL] = script.PUBLIC
        with patched(script, fake):
            self.assertTrue(script.provision("key"))
        self.assertEqual(fake.grants[AUDIO_MODEL], [])

    def test_negative_control_without_the_mode_filter_the_audio_route_is_public(self):
        script = load_script()
        fake = FakeOpenWebUI({CHAT_MODEL: "chat", AUDIO_MODEL: "audio_transcription"})
        with patched(script, fake), patch.object(script, "UNGRANTED_MODES", ()):
            script.provision("key")
        self.assertEqual(fake.grants[AUDIO_MODEL], script.PUBLIC)


if __name__ == "__main__":
    unittest.main()
