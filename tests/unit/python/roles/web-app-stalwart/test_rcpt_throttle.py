from __future__ import annotations

import json
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-stalwart"
TASKS = load_yaml_any(str(ROLE / "tasks" / "throttle.yml"), default_if_missing=[])
MANAGER_OPS = load_yaml_any(
    str(ROLE / "tasks" / "manager_ops.yml"), default_if_missing=[]
)
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
RULE = VARS["STALWART_RCPT_THROTTLE_RULE"]

SENDER_IP = {
    "id": "a",
    "description": "Sender IP throttle",
    "enable": True,
    "key": {"remoteIp": True},
    "match": {"match": {}, "else": ""},
    "rate": {"count": 5, "period": 1000},
}
RECIPIENT = {
    "id": "b",
    "description": "Sender address to recipient throttle",
    "enable": True,
    "key": {"senderDomain": True, "rcpt": True},
    "match": {"match": {}, "else": ""},
    "rate": {"count": 25, "period": 3600000},
}


def _render(template: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _selected(throttles: list[dict]) -> list[str]:
    facts = next(
        task["ansible.builtin.set_fact"]
        for task in TASKS
        if "ansible.builtin.set_fact" in task
    )
    return _render(
        facts["stalwart_rcpt_throttle_ids"],
        STALWART_RCPT_THROTTLE_KEY=VARS["STALWART_RCPT_THROTTLE_KEY"],
        STALWART_RCPT_THROTTLE_RULE=RULE,
        stalwart_jmap={
            "methodResponses": [["x:MtaInboundThrottle/get", {"list": throttles}, "c0"]]
        },
    )


def _update_body(ids: list[str]) -> dict:
    block = next(task["block"] for task in TASKS if "block" in task)
    return json.loads(
        _render(
            block[0]["vars"]["stalwart_jmap_body"],
            stalwart_rcpt_throttle_ids=ids,
            STALWART_RCPT_THROTTLE_RULE=RULE,
        )
    )


class TestRecipientThrottle(unittest.TestCase):
    def test_only_the_recipient_throttle_is_selected(self):
        self.assertEqual(_selected([SENDER_IP, RECIPIENT]), ["b"])

    def test_a_limited_recipient_throttle_is_left_alone(self):
        limited = {**RECIPIENT, "match": {"match": {}, "else": RULE}}
        self.assertEqual(_selected([SENDER_IP, limited]), [])

    def test_the_update_counts_only_unauthenticated_sessions(self):
        self.assertEqual(
            _update_body(["b"])["methodCalls"],
            [
                [
                    "x:MtaInboundThrottle/set",
                    {
                        "update": {
                            "b": {"match": {"else": "is_empty(authenticated_as)"}}
                        }
                    },
                    "c0",
                ]
            ],
        )

    def test_the_rule_is_the_complement_of_the_relay_rule(self):
        self.assertEqual(VARS["STALWART_RELAY_RULE"], "!" + RULE)

    def test_the_settings_reload_after_the_update(self):
        block = next(task["block"] for task in TASKS if "block" in task)
        self.assertEqual(
            block[-1]["vars"]["stalwart_jmap_body"],
            "{{ STALWART_JMAP_RELOAD_SETTINGS }}",
        )

    def test_the_manager_runs_the_throttle_tasks(self):
        self.assertIn(
            "throttle.yml", [task.get("include_tasks") for task in MANAGER_OPS]
        )


if __name__ == "__main__":
    unittest.main()
