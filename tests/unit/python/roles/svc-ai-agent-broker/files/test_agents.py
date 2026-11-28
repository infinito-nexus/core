from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import unittest
import unittest.mock
import urllib.error

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

BROKER_DIR = PROJECT_ROOT / "roles/svc-ai-agent-broker/files/python"
sys.path.insert(0, str(BROKER_DIR))

import engine  # noqa: E402

_AGENTS_SPEC = importlib.util.spec_from_file_location(
    "broker_agents", BROKER_DIR / "agents.py"
)
agents = importlib.util.module_from_spec(_AGENTS_SPEC)
_AGENTS_SPEC.loader.exec_module(agents)

HERMES_RENDER = {
    "model": {
        "default": "${model}",
        "provider": "custom",
        "base_url": "${relay_url}",
        "api_key": "${key}",
        "context_length": "${context}",
    },
    "mcp_servers": {},
}
OPENCLAW_RENDER = {
    "gateway": {
        "mode": "local",
        "http": {"endpoints": {"chatCompletions": {"enabled": True}}},
    },
    "agents": {"defaults": {"model": {"primary": "broker/${model}"}}},
    "models": {
        "providers": {
            "broker": {
                "baseUrl": "${relay_url}",
                "apiKey": "${key}",
                "api": "openai-completions",
                "models": [
                    {
                        "id": "${model}",
                        "name": "${model}",
                        "contextWindow": "${context}",
                    }
                ],
            }
        }
    },
}
PLATFORMS = {
    "hermes": {
        "image": "nousresearch/hermes-agent:v1",
        "command": ["gateway"],
        "env": {"API_SERVER_PORT": "8642"},
        "key_env": "API_SERVER_KEY",
        "config_path": "/opt/data/config.yaml",
        "config_render": HERMES_RENDER,
        "data": "/opt/data",
        "user": "",
        "cpus": "2.0",
        "mem_limit": 4294967296,
        "mem_reservation": 2147483648,
        "pids_limit": "2048",
        "port": "8642",
        "health": "/health",
        "request_model": "hermes-agent",
    },
    "openclaw": {"config_render": OPENCLAW_RENDER},
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


class FakeStartBackend(FakeBackend):
    def __init__(self, details):
        super().__init__(details)
        self.started = []

    def network_for(self, name, labels, self_container, broker_alias):
        return name

    def create(self, spec, network_id):
        detail = {"Name": f"/{spec['name']}", "running": False, "env": spec["env"]}
        self.details[spec["name"]] = detail
        return detail

    def start(self, detail, network_id):
        self.started.append(detail["Name"].lstrip("/"))
        detail["running"] = True

    def labels_of(self, detail):
        return {}

    def env_of(self, detail):
        return detail.get("env", [])


def make_agents(
    backend=None, idle_stop=True, context=0, log=None, max_running=2, queue_timeout=5
):
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
        max_running=max_running,
        start_timeout=10,
        queue_timeout=queue_timeout,
        log=log or (lambda event, **fields: None),
    )


class TestPick(unittest.TestCase):
    def test_a_known_platform_resolves_to_the_configured_name(self):
        requested = json.loads('{"model": "hermes"}')["model"]
        picked = agents.pick(requested, PLATFORMS)
        self.assertEqual(picked, "hermes")
        self.assertIs(picked, next(iter(PLATFORMS)))

    def test_an_unknown_or_unhashable_platform_resolves_to_none(self):
        for requested in ("unlisted", None, 7, ["hermes"], {"hermes": 1}):
            with self.subTest(requested=requested):
                self.assertIsNone(agents.pick(requested, PLATFORMS))

    def test_the_relay_passes_the_paths_the_agents_use(self):
        for path in ("/v1/chat/completions", "/v1/models"):
            with self.subTest(path=path):
                self.assertEqual(agents.pick(path, agents.RELAY_PATHS), path)

    def test_the_relay_refuses_every_other_gateway_route(self):
        for path in (
            "/key/generate",
            "/v1/../key/generate",
            "/v1/chat/completions?x=1",
            "/v1/embeddings",
            "/api/tags",
            "",
        ):
            with self.subTest(path=path):
                self.assertIsNone(agents.pick(path, agents.RELAY_PATHS))


AGENT_ROLES_DIR = PROJECT_ROOT / "agents" / "roles"


def real_role_runtimes():
    return {
        path.parent.name: load_yaml_any(str(path))["runtime"]
        for path in sorted(AGENT_ROLES_DIR.glob("*/agent.yml"))
    }


class TestProfileCatalog(unittest.TestCase):
    def test_every_agent_role_is_listed_as_an_agent_model(self):
        roles = real_role_runtimes()
        self.assertTrue(roles)
        listed = [
            entry["id"]
            for entry in agents.model_list(PLATFORMS, agents.profile_catalog(roles))
        ]
        for role in roles:
            with self.subTest(role=role):
                self.assertIn(f"agent/{role}", listed)
        self.assertEqual(listed[:2], ["hermes", "openclaw"])

    def test_a_profile_resolves_to_its_runtime_and_an_agent_of_its_own(self):
        profiles = agents.profile_catalog(
            {"planner": "hermes", "tester": "claude-code"}
        )
        self.assertEqual(
            agents.resolve("agent/planner", PLATFORMS, profiles),
            ("hermes", "hermes-planner"),
        )
        self.assertEqual(
            agents.resolve("hermes", PLATFORMS, profiles), ("hermes", "hermes")
        )
        self.assertNotEqual(
            agents.agent_name("hermes-planner", "u1"), agents.agent_name("hermes", "u1")
        )

    def test_a_profile_on_a_runtime_not_offered_or_an_unknown_model_resolves_to_none(
        self,
    ):
        profiles = agents.profile_catalog({"tester": "claude-code"})
        self.assertEqual(
            agents.resolve("agent/tester", PLATFORMS, profiles),
            (None, "claude-code-tester"),
        )
        for requested in ("agent/unlisted", "agent/", None, ["agent/tester"]):
            with self.subTest(requested=requested):
                self.assertEqual(
                    agents.resolve(requested, PLATFORMS, profiles), (None, None)
                )

    def test_a_profile_agent_is_spawned_from_its_runtime_under_its_own_name(self):
        spec = make_agents()._spec("hermes", "owner", "secret", "hermes-planner")
        self.assertEqual(spec["name"], agents.agent_name("hermes-planner", "owner"))
        self.assertEqual(spec["labels"][engine.LABEL_PLATFORM], "hermes")
        self.assertEqual(spec["image"], PLATFORMS["hermes"]["image"])

    def test_the_broker_env_carries_every_agent_role_and_its_runtime(self):
        broker = PROJECT_ROOT / "roles" / "svc-ai-agent-broker"
        env = read_text(str(broker / "templates" / "env.j2"))
        self.assertIn(
            "AGENT_ROLES={{ AGENT_BROKER_ROLE_RUNTIMES | to_json | dotenv_quote }}", env
        )
        variables = load_yaml_any(str(broker / ROLE_FILE_VARS_MAIN))
        collected = {
            role: {"runtime": runtime, "lifecycle": "on_demand"}
            for role, runtime in real_role_runtimes().items()
        }
        rendered = Templar(
            loader=DataLoader(), variables={"vm_capacity_agents": collected}
        ).template(trust_as_template(variables["AGENT_BROKER_ROLE_RUNTIMES"]))
        self.assertEqual(rendered, real_role_runtimes())


class TestAgentCalls(unittest.TestCase):
    def test_an_agent_that_never_answers_names_its_last_error(self):
        broker = make_agents()
        refused = urllib.error.URLError("connection refused")
        with (
            unittest.mock.patch.object(
                agents.urllib.request, "urlopen", side_effect=refused
            ),
            unittest.mock.patch.object(
                agents.time, "monotonic", side_effect=[0, 0, 100]
            ),
            unittest.mock.patch.object(agents.time, "sleep"),
            self.assertRaises(TimeoutError) as caught,
        ):
            broker._wait_healthy("hermes", "agent-hermes-1", "k")
        self.assertIn("connection refused", str(caught.exception))

    def test_an_unlisted_agent_model_falls_back_and_is_logged(self):
        events = []
        broker = make_agents(log=lambda event, **fields: events.append((event, fields)))
        refused = urllib.error.URLError("connection refused")
        with unittest.mock.patch.object(
            agents.urllib.request, "urlopen", side_effect=refused
        ):
            model = broker.agent_model("hermes", "http://agent-hermes-1:8642", "k")
        self.assertEqual(model, "hermes-agent")
        self.assertEqual(len(events), 1)
        event, fields = events[0]
        self.assertEqual(event, "agent_model_fallback")
        self.assertEqual(fields["platform"], "hermes")
        self.assertEqual(fields["model"], "hermes-agent")
        self.assertIn("connection refused", fields["error"])


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
            agents.render_config(PLATFORMS["hermes"], "m", "http://relay/v1", "k", 0)
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
        config = json.loads(
            agents.render_config(PLATFORMS["openclaw"], "m", "http://relay/v1", "k", 0)
        )
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
            agents.render_config(
                PLATFORMS["hermes"], "m", "http://relay/v1", "k", 32768
            )
        )  # nocheck: direct-yaml - parses this test's own render
        self.assertEqual(hermes["model"]["context_length"], 32768)
        openclaw = json.loads(
            agents.render_config(
                PLATFORMS["openclaw"], "m", "http://relay/v1", "k", 32768
            )
        )
        entry = openclaw["models"]["providers"]["broker"]["models"][0]
        self.assertEqual(entry["contextWindow"], 32768)

    def test_an_unknown_window_leaves_the_agents_to_their_own_default(self):
        hermes = yaml.safe_load(
            agents.render_config(PLATFORMS["hermes"], "m", "http://relay/v1", "k", 0)
        )  # nocheck: direct-yaml - parses this test's own render
        self.assertNotIn("context_length", hermes["model"])
        openclaw = json.loads(
            agents.render_config(PLATFORMS["openclaw"], "m", "http://relay/v1", "k", 0)
        )
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


class CountingBackend(FakeStartBackend):
    def __init__(self, details):
        super().__init__(details)
        self.listed = 0

    def list_agents(self):
        self.listed += 1
        return super().list_agents()


class TestOwnerOfKey(unittest.TestCase):
    def setUp(self):
        self.backend = CountingBackend(
            {
                "agent-hermes-1": {
                    "Name": "/agent-hermes-1",
                    "running": False,
                    "env": [f"{agents.KEY_ENV}=known"],
                }
            }
        )
        self.broker = make_agents(self.backend)

    def test_an_agent_from_before_a_restart_is_found_on_the_first_miss(self):
        self.assertIsNotNone(self.broker.owner_of_key("known"))
        self.assertEqual(self.backend.listed, 1)

    def test_unknown_keys_read_the_agents_once_per_window(self):
        for junk in ("junk-1", "junk-2", "junk-3"):
            self.assertIsNone(self.broker.owner_of_key(junk))
        self.assertEqual(self.backend.listed, 1)

    def test_a_miss_after_the_window_reads_the_agents_again(self):
        self.broker.owner_of_key("junk-1")
        self.broker._keys_refreshed -= agents.KEYS_REFRESH_SECONDS
        self.broker.owner_of_key("junk-2")
        self.assertEqual(self.backend.listed, 2)

    def test_a_failed_read_leaves_the_window_open(self):
        failing = self.backend.list_agents

        def fail_once():
            self.backend.list_agents = failing
            raise RuntimeError("engine gone")

        self.backend.list_agents = fail_once
        with self.assertRaises(RuntimeError):
            self.broker.owner_of_key("known")
        self.assertIsNotNone(self.broker.owner_of_key("known"))

    def test_an_agent_started_inside_the_window_is_known_without_a_read(self):
        self.broker._wait_healthy = lambda platform, name, key: None
        self.broker.owner_of_key("junk-1")
        _, key = self.broker.ensure("hermes", "a")
        listed = self.backend.listed
        self.assertIsNotNone(self.broker.owner_of_key(key))
        self.assertEqual(self.backend.listed, listed)


class TestStartQueue(unittest.TestCase):
    def setUp(self):
        self.busy = agents.agent_name("hermes", "busy")
        self.backend = FakeStartBackend(
            {self.busy: {"Name": f"/{self.busy}", "running": True, "env": []}}
        )
        self.broker = make_agents(self.backend, max_running=1)
        self.broker._wait_healthy = lambda platform, name, key: None
        self.errors = []

    def start(self, owner):
        def run():
            try:
                self.broker.ensure("hermes", owner)
            except agents.CapacityError as error:
                self.errors.append(error)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            self.assertLess(time.monotonic(), deadline, "condition never held")
            time.sleep(0.01)

    def test_a_start_beyond_max_running_waits_and_runs_when_a_slot_frees(self):
        waiting = self.start("a")
        self.wait_for(lambda: len(self.broker._queue) == 1)
        self.assertEqual(self.backend.started, [])
        self.broker.stop_owner("hermes", "busy")
        waiting.join(5)
        self.assertEqual(self.errors, [])
        self.assertEqual(self.backend.started, [agents.agent_name("hermes", "a")])

    def test_queued_starts_run_in_trigger_order(self):
        first = self.start("a")
        self.wait_for(lambda: len(self.broker._queue) == 1)
        second = self.start("b")
        self.wait_for(lambda: len(self.broker._queue) == 2)
        self.broker.stop_owner("hermes", "busy")
        first.join(5)
        self.assertEqual(self.backend.started, [agents.agent_name("hermes", "a")])
        self.assertEqual(len(self.broker._queue), 1)
        self.broker.stop_owner("hermes", "a")
        second.join(5)
        self.assertEqual(
            self.backend.started,
            [agents.agent_name("hermes", "a"), agents.agent_name("hermes", "b")],
        )
        self.assertEqual(self.errors, [])

    def test_a_start_that_outwaits_the_queue_timeout_is_refused(self):
        self.broker.queue_timeout = 0
        with self.assertRaises(agents.CapacityError) as caught:
            self.broker.ensure("hermes", "a")
        self.assertIn("start queue", str(caught.exception))
        self.assertEqual(len(self.broker._queue), 0)
        self.assertEqual(self.broker._starting, 0)


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
