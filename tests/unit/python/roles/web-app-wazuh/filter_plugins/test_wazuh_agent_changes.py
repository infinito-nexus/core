import base64
import importlib.util
import json
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "wazuh_agent_changes",
    PROJECT_ROOT / "roles" / "web-app-wazuh" / "filter_plugins" / "wazuh_agent_changes.py",
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
wazuh_agent_changes = _module.wazuh_agent_changes

KEY = "a" * 64
AGENT = {"id": "001", "name": "host.example", "key": KEY}


def registered(agent_id, name, key):
    blob = base64.b64encode(f"{agent_id} {name} any {key}".encode()).decode()
    body = {
        "data": {
            "affected_items": [{"id": agent_id, "key": blob}],
            "total_affected_items": 1,
            "total_failed_items": 0,
            "failed_items": [],
        },
        "error": 0,
    }
    return json.dumps(body)


def missing(agent_id, code=1701):
    body = {
        "data": {
            "affected_items": [],
            "total_affected_items": 0,
            "total_failed_items": 1,
            "failed_items": [{"error": {"code": code}, "id": [agent_id]}],
        },
        "error": 1,
    }
    return json.dumps(body)


def result(agent, stdout):
    return {"item": agent, "stdout": stdout}


class TestWazuhAgentChanges(unittest.TestCase):
    def test_unknown_agent_is_inserted(self):
        changes = wazuh_agent_changes([AGENT], [result(AGENT, missing("001"))])
        self.assertEqual(changes, [{**AGENT, "action": "insert"}])

    def test_matching_agent_needs_no_change(self):
        changes = wazuh_agent_changes(
            [AGENT], [result(AGENT, registered("001", "host.example", KEY))]
        )
        self.assertEqual(changes, [])

    def test_different_key_is_replaced(self):
        changes = wazuh_agent_changes(
            [AGENT], [result(AGENT, registered("001", "host.example", "b" * 64))]
        )
        self.assertEqual(changes, [{**AGENT, "action": "replace"}])

    def test_different_name_is_replaced(self):
        changes = wazuh_agent_changes(
            [AGENT], [result(AGENT, registered("001", "old.example", KEY))]
        )
        self.assertEqual(changes, [{**AGENT, "action": "replace"}])

    def test_only_changed_agents_are_returned(self):
        other = {"id": "002", "name": "other.example", "key": "c" * 64}
        changes = wazuh_agent_changes(
            [AGENT, other],
            [
                result(AGENT, registered("001", "host.example", KEY)),
                result(other, missing("002")),
            ],
        )
        self.assertEqual(changes, [{**other, "action": "insert"}])

    def test_unauthorized_response_fails(self):
        body = json.dumps({"title": "Unauthorized", "detail": "Invalid token"})
        with self.assertRaises(AnsibleFilterError):
            wazuh_agent_changes([AGENT], [result(AGENT, body)])

    def test_other_lookup_error_fails(self):
        with self.assertRaises(AnsibleFilterError):
            wazuh_agent_changes([AGENT], [result(AGENT, missing("001", code=1000))])

    def test_error_message_does_not_carry_the_key(self):
        with self.assertRaises(AnsibleFilterError) as ctx:
            wazuh_agent_changes([AGENT], [result(AGENT, missing("001", code=1000))])
        self.assertNotIn(KEY, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
