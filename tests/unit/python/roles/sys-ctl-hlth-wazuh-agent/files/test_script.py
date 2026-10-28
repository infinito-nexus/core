import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase, main

import jinja2

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "sys-ctl-hlth-wazuh-agent"
    / "files"
    / "python"
    / "script.py"
)
ROLE_VARS = PROJECT_ROOT / "roles" / "sys-ctl-hlth-wazuh-agent" / ROLE_FILE_VARS_MAIN
AGENT_VARS = PROJECT_ROOT / "roles" / "sys-svc-wazuh-agent" / ROLE_FILE_VARS_MAIN
NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC).astimezone()
THRESHOLD = 180


def render(role_vars, name):
    """Return a role var with its path_join references resolved.

    Args:
        role_vars: the role's vars/main.yml.
        name: the var to resolve.
    """
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)  # noqa: S701 - renders file paths, not HTML
    environment.filters["path_join"] = lambda parts: str(Path(*parts))
    value = role_vars[name]
    while isinstance(value, str) and "{{" in value:
        value = environment.from_string(value).render(role_vars)
    return value


LISTING = """Wazuh agent_control. List of available agents:
   ID: 000, Name: wazuh.manager (server), IP: 127.0.0.1, Active/Local
   ID: 001, Name: infinito.test, IP: any, Active
   ID: 002, Name: web2.example, IP: any, Never connected
   ID: 003, Name: web3.example, IP: any, Disconnected
"""


def load_script():
    spec = importlib.util.spec_from_file_location("hlth_wazuh_agent", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state(status, ack_seconds_ago, buffered="0"):
    return {
        "status": status,
        "last_ack": (NOW - timedelta(seconds=ack_seconds_ago)).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "msg_buffer": buffered,
    }


class TestEvaluateHost(TestCase):
    def setUp(self):
        self.script = load_script()

    def evaluate(self, service_active=True, agentd_age=3600, agent_state=None):
        return self.script.evaluate_host(
            service_active, agentd_age, agent_state, NOW, THRESHOLD
        )

    def test_connected_agent_is_healthy(self):
        self.assertEqual(self.evaluate(agent_state=state("connected", 5)), [])

    def test_inactive_service_fails(self):
        self.assertEqual(
            self.evaluate(service_active=False), ["the agent service is not active"]
        )

    def test_active_unit_without_agentd_fails(self):
        problems = self.evaluate(agentd_age=None, agent_state=state("connected", 5))
        self.assertIn("wazuh-agentd is not running", problems[0])

    def test_short_disconnect_is_tolerated(self):
        self.assertEqual(self.evaluate(agent_state=state("disconnected", 30)), [])

    def test_long_disconnect_fails_with_ack_age_and_buffer(self):
        problems = self.evaluate(
            agent_state=state("disconnected", 600, buffered="4870")
        )
        self.assertEqual(
            problems,
            [
                "wazuh-agentd is disconnected: last manager ACK 600 s ago (threshold 180 s), 4870 events buffered"
            ],
        )

    def test_fresh_agentd_is_in_grace(self):
        self.assertEqual(
            self.evaluate(agentd_age=20, agent_state=state("pending", 900)), []
        )

    def test_missing_state_after_grace_fails(self):
        self.assertEqual(
            self.evaluate(agent_state=None), ["wazuh-agentd has written no state file"]
        )

    def test_unparsable_ack_counts_as_never(self):
        problems = self.evaluate(
            agent_state={"status": "pending", "last_ack": "", "msg_buffer": "0"}
        )
        self.assertIn("last manager ACK never", problems[0])


class TestEvaluateManager(TestCase):
    def setUp(self):
        self.script = load_script()
        self.now_epoch = 1_800_000_000

    def evaluate(self, listing=LISTING, keepalives=None, since_change=3600):
        return self.script.evaluate_manager(
            listing, keepalives or {}, since_change, self.now_epoch, THRESHOLD
        )

    def test_unreachable_manager_fails(self):
        self.assertEqual(
            self.evaluate(listing=None), ["the Wazuh manager is unreachable"]
        )

    def test_unknown_manager_container_fails(self):
        self.assertEqual(
            self.evaluate(listing=None, since_change=None),
            ["the Wazuh manager is unreachable"],
        )

    def test_recently_stopped_manager_is_in_grace(self):
        self.assertEqual(self.evaluate(listing=None, since_change=60), [])

    def test_never_connected_and_long_disconnected_agents_fail(self):
        problems = self.evaluate(keepalives={"002": None, "003": self.now_epoch - 900})
        self.assertEqual(
            problems,
            [
                "agent 002 (web2.example) is Never connected: last keepalive never (threshold 180 s)",
                "agent 003 (web3.example) is Disconnected: last keepalive 900 s ago (threshold 180 s)",
            ],
        )

    def test_recent_keepalive_is_tolerated(self):
        problems = self.evaluate(
            keepalives={"002": self.now_epoch - 10, "003": self.now_epoch - 10}
        )
        self.assertEqual(problems, [])

    def test_recently_started_manager_is_in_grace(self):
        self.assertEqual(self.evaluate(keepalives={"002": None}, since_change=30), [])

    def test_all_active_is_healthy(self):
        listing = "   ID: 000, Name: m (server), IP: 127.0.0.1, Active/Local\n   ID: 001, Name: a, IP: any, Active\n"
        self.assertEqual(self.evaluate(listing=listing), [])


class TestEvaluateClock(TestCase):
    def setUp(self):
        self.script = load_script()

    def test_synchronized_clock_is_healthy(self):
        self.assertEqual(self.script.evaluate_clock("yes"), [])

    def test_unsynchronized_clock_fails(self):
        self.assertIn("NTPSynchronized=no", self.script.evaluate_clock("no")[0])

    def test_unreadable_clock_state_fails(self):
        self.assertIn("NTPSynchronized=unreadable", self.script.evaluate_clock(None)[0])


class TestEvaluateCollector(TestCase):
    def setUp(self):
        self.script = load_script()

    def test_frozen_collector_while_online_fails(self):
        self.assertIn("frozen", self.script.evaluate_collector("T", False)[0])

    def test_frozen_collector_while_offline_is_expected(self):
        self.assertEqual(self.script.evaluate_collector("T", True), [])

    def test_running_collector_is_healthy(self):
        for state in ("S", "R"):
            for locked in (True, False):
                with self.subTest(state=state, locked=locked):
                    self.assertEqual(self.script.evaluate_collector(state, locked), [])

    def test_missing_collector_is_left_to_the_service_check(self):
        self.assertEqual(self.script.evaluate_collector(None, False), [])


class TestParsing(TestCase):
    def setUp(self):
        self.script = load_script()

    def test_state_file_is_parsed(self):
        text = "# comment\nstatus='connected'\nlast_ack='2026-10-18 21:41:52'\nmsg_buffer='0'\n"
        self.assertEqual(
            self.script.parse_state(text),
            {
                "status": "connected",
                "last_ack": "2026-10-18 21:41:52",
                "msg_buffer": "0",
            },
        )

    def test_agent_lines_are_parsed(self):
        self.assertEqual(
            self.script.parse_agents(LISTING)[2],
            ("002", "web2.example", "Never connected"),
        )

    def test_call_without_wait_file_and_grace_uses_the_role_values(self):
        args = self.script.parse_args(
            [
                "--service",
                "wazuh-agent.service",
                "--run-dir",
                "/var/ossec/var/run",
                "--threshold",
                "180",
            ]
        )
        role_vars = load_yaml(str(ROLE_VARS))
        agent_vars = load_yaml(str(AGENT_VARS))
        self.assertEqual(
            args.wait_file,
            render(agent_vars, "WAZUH_AGENT_WAIT_FILE"),
        )
        self.assertEqual(
            args.collector_grace, role_vars["HLTH_WAZUH_AGENT_COLLECTOR_GRACE"]
        )

    def test_script_never_reads_keys(self):
        self.assertNotIn("client.keys", read_text(str(SCRIPT)))


if __name__ == "__main__":
    main()
