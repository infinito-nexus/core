from __future__ import annotations

import importlib.util
import json
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = (
    PROJECT_ROOT / "roles/web-app-openwebui/files/python/agent_model_grants.py"
)
AGENT_MODELS = {
    "hermes": "/roles/web-app-hermes/agent-user",
    "openclaw": "/roles/web-app-openclaw/agent-user",
}


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
        },
    ):
        spec.loader.exec_module(module)
    return module


class FakeOpenWebUI:
    def __init__(self, gateway_models):
        self.gateway_models = gateway_models
        self.grants = {}
        self.groups = {}

    def call(self, url, key, payload=None):
        if url.endswith("/v1/models"):
            return 200, {"data": [{"id": model} for model in self.gateway_models]}
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


class TestProvision(unittest.TestCase):
    def test_gateway_models_become_public_and_agents_stay_in_their_group(self):
        script = load_script()
        fake = FakeOpenWebUI(["qwen2.5:0.5b", "hermes"])
        with patched(script, fake):
            self.assertTrue(script.provision("key"))
        self.assertEqual(fake.grants["qwen2.5:0.5b"], script.PUBLIC)
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
        fake = FakeOpenWebUI(["qwen2.5:0.5b"])
        with patched(script, fake):
            script.provision("key")
            self.assertFalse(script.provision("key"))

    def test_without_a_gateway_only_the_agents_are_granted(self):
        script = load_script(gateway_url="")
        fake = FakeOpenWebUI(["qwen2.5:0.5b"])
        with patched(script, fake):
            script.provision("key")
        self.assertEqual(set(fake.grants), set(AGENT_MODELS))


if __name__ == "__main__":
    unittest.main()
