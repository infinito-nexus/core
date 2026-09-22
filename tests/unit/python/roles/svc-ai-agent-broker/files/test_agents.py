from __future__ import annotations

import json
import sys
import unittest

import yaml

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/svc-ai-agent-broker/files/python"))

import agents
import engine

PLATFORMS = {
    "hermes": {
        "image": "nousresearch/hermes-agent:v1",
        "command": ["gateway"],
        "env": {"API_SERVER_PORT": "8642"},
        "key_env": "API_SERVER_KEY",
        "config_path": "/opt/data/config.yaml",
        "data": "/opt/data",
        "user": "",
        "cpus": "2.0",
        "mem_limit": 4294967296,
        "mem_reservation": 2147483648,
        "pids_limit": "2048",
        "port": "8642",
        "health": "/health",
        "request_model": "hermes-agent",
    }
}


class FakeEngine:
    def __init__(self, runtime="runsc"):
        self.calls = []
        self.runtime = runtime

    def image_config(self, ref):
        return ["/entrypoint.sh"], ["serve"]

    def call(self, method, path, body=None, query=None, expect=(200,)):
        self.calls.append((method, path))
        return {"Id": "abc", "Name": "/agent", "HostConfig": {"Runtime": self.runtime}}


def make_agents():
    return agents.Agents(
        backend=None,
        engine=FakeEngine(),
        platforms=PLATFORMS,
        self_container="self",
        broker_alias="agent-broker",
        relay_url="http://agent-broker:8080/llm/v1",
        model="qwen2.5:0.5b",
        idle_stop=True,
        idle_seconds=60,
        max_running=2,
        start_timeout=10,
    )


class TestNaming(unittest.TestCase):
    def test_one_owner_one_name_two_owners_two_names(self):
        self.assertEqual(
            agents.agent_name("hermes", "u1"), agents.agent_name("hermes", "u1")
        )
        self.assertNotEqual(
            agents.agent_name("hermes", "u1"), agents.agent_name("hermes", "u2")
        )
        self.assertNotEqual(
            agents.agent_name("hermes", "u1"), agents.agent_name("openclaw", "u1")
        )


class TestConfigs(unittest.TestCase):
    def test_hermes_points_its_custom_provider_at_the_relay(self):
        config = yaml.safe_load(
            agents.hermes_config("m", "http://relay/v1", "k")
        )  # nocheck: direct-yaml - parses this test's own render
        self.assertEqual(
            config["model"],
            {
                "default": "m",
                "provider": "custom",
                "base_url": "http://relay/v1",
                "api_key": "k",
            },
        )

    def test_openclaw_enables_chat_completions_and_the_relay_provider(self):
        config = json.loads(agents.openclaw_config("m", "http://relay/v1", "k"))
        self.assertTrue(
            config["gateway"]["http"]["endpoints"]["chatCompletions"]["enabled"]
        )
        self.assertEqual(
            config["models"]["providers"]["broker"]["baseUrl"], "http://relay/v1"
        )
        self.assertEqual(config["agents"]["defaults"]["model"]["primary"], "broker/m")


class TestSpec(unittest.TestCase):
    def test_the_config_is_written_before_the_image_entrypoint_runs(self):
        spec = make_agents()._spec("hermes", "owner", "secret")
        self.assertEqual(spec["entrypoint"][:2], ["/bin/sh", "-c"])
        self.assertEqual(spec["cmd"], ["/entrypoint.sh", "gateway"])
        self.assertIn("API_SERVER_KEY=secret", spec["env"])
        self.assertIn(f"{agents.CONFIG_PATH_ENV}=/opt/data/config.yaml", spec["env"])
        self.assertEqual(spec["labels"][engine.LABEL_OWNER], "owner")
        self.assertEqual(spec["nano_cpus"], 2_000_000_000)

    def test_a_numeric_command_argument_reaches_the_engine_as_a_string(self):
        broker = make_agents()
        broker.platforms = {
            "hermes": {**PLATFORMS["hermes"], "command": ["run", "--port", 18789]}
        }
        spec = broker._spec("hermes", "owner", "secret")
        self.assertEqual(spec["cmd"], ["/entrypoint.sh", "run", "--port", "18789"])


if __name__ == "__main__":
    unittest.main()
