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


class FakeBackend:
    def __init__(self, details):
        self.details = details
        self.stopped = []

    def list_agents(self):
        return list(self.details.values())

    def find(self, name):
        return self.details.get(name)

    def is_running(self, detail):
        return detail["running"]

    def started_at(self, detail):
        return detail["started_at"]

    def stop(self, detail):
        self.stopped.append(detail["Name"].lstrip("/"))
        detail["running"] = False


def make_agents(backend=None, idle_stop=True, context=0):
    return agents.Agents(
        backend=backend,
        engine=FakeEngine(),
        platforms=PLATFORMS,
        self_container="self",
        broker_alias="agent-broker",
        relay_url="http://agent-broker:8080/llm/v1",
        model="qwen2.5:0.5b",
        context=context,
        idle_stop=idle_stop,
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
            agents.hermes_config("m", "http://relay/v1", "k", 0)
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
        config = json.loads(agents.openclaw_config("m", "http://relay/v1", "k", 0))
        self.assertTrue(
            config["gateway"]["http"]["endpoints"]["chatCompletions"]["enabled"]
        )
        self.assertEqual(
            config["models"]["providers"]["broker"]["baseUrl"], "http://relay/v1"
        )
        self.assertEqual(config["agents"]["defaults"]["model"]["primary"], "broker/m")


class TestContextWindow(unittest.TestCase):
    def test_a_known_window_reaches_both_agent_configs(self):
        hermes = yaml.safe_load(
            agents.hermes_config("m", "http://relay/v1", "k", 32768)
        )  # nocheck: direct-yaml - parses this test's own render
        self.assertEqual(hermes["model"]["context_length"], 32768)
        openclaw = json.loads(
            agents.openclaw_config("m", "http://relay/v1", "k", 32768)
        )
        entry = openclaw["models"]["providers"]["broker"]["models"][0]
        self.assertEqual(entry["contextWindow"], 32768)

    def test_an_unknown_window_leaves_the_agents_to_their_own_default(self):
        hermes = yaml.safe_load(
            agents.hermes_config("m", "http://relay/v1", "k", 0)
        )  # nocheck: direct-yaml - parses this test's own render
        self.assertNotIn("context_length", hermes["model"])
        openclaw = json.loads(agents.openclaw_config("m", "http://relay/v1", "k", 0))
        self.assertNotIn(
            "contextWindow", openclaw["models"]["providers"]["broker"]["models"][0]
        )


class TestReap(unittest.TestCase):
    def detail(self, name, running=True, started="2020-01-01T00:00:00.000000000Z"):
        return {"Name": f"/{name}", "running": running, "started_at": started}

    def test_an_idle_agent_is_stopped(self):
        backend = FakeBackend({"agent-hermes-1": self.detail("agent-hermes-1")})
        make_agents(backend).reap()
        self.assertEqual(backend.stopped, ["agent-hermes-1"])

    def test_idle_stop_false_stops_nothing(self):
        backend = FakeBackend({"agent-hermes-1": self.detail("agent-hermes-1")})
        make_agents(backend, idle_stop=False).reap()
        self.assertEqual(backend.stopped, [])

    def test_an_agent_serving_a_request_survives_its_idle_time(self):
        backend = FakeBackend({"agent-hermes-1": self.detail("agent-hermes-1")})
        broker = make_agents(backend)
        broker._busy["agent-hermes-1"] = 1
        broker.reap()
        self.assertEqual(backend.stopped, [])

    def test_a_prompt_that_lands_during_the_sweep_keeps_the_agent(self):
        backend = FakeBackend({"agent-hermes-1": self.detail("agent-hermes-1")})
        broker = make_agents(backend)
        original = broker._lock_for

        def touch_then_lock(name):
            broker.end(name)
            return original(name)

        broker._lock_for = touch_then_lock
        broker.reap()
        self.assertEqual(backend.stopped, [])


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
