"""The shared Stalwart JMAP call: what it rejects and what it puts on argv.

A set-level rejection (``notCreated``/``notUpdated``) arrives inside a normal
method response, so checking only for an ``error`` method lets a refused
create pass as success. The admin password and the request body carry
secrets, so neither may reach curl's command line.
"""

from __future__ import annotations

import json
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

TASK = PROJECT_ROOT / "roles" / "web-app-stalwart" / "tasks" / "jmap_call.yml"

PASSWORD = 'p"a\\s$s`w#o[r]d é'


def _tasks() -> list[dict]:
    return load_yaml_any(str(TASK), default_if_missing=[])


def _module(task: dict, name: str) -> dict:
    return task.get(f"ansible.builtin.{name}") or task.get(name) or {}


def _call_task() -> dict:
    return next(_module(t, "shell") for t in _tasks() if _module(t, "shell"))


def _assert_task() -> dict:
    return next(t for t in _tasks() if _module(t, "assert"))


def _render(template: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _accepted(response: list, **extra) -> bool:
    task = _assert_task()
    variables = {"stalwart_jmap": {"methodResponses": [response]}, **extra}
    for name, raw in (task.get("vars") or {}).items():
        variables[name] = _render(raw, **variables)
    return all(
        _render("{{ (" + expr + ") | bool }}", **variables)
        for expr in _module(task, "assert")["that"]
    )


class TestJmapRejectionIsAFailure(unittest.TestCase):
    def test_a_clean_set_passes(self):
        self.assertTrue(
            _accepted(["x:Domain/set", {"created": {"d": {"id": "1"}}}, "c0"])
        )

    def test_null_rejection_maps_pass(self):
        self.assertTrue(
            _accepted(
                ["x:Domain/set", {"notCreated": None, "notUpdated": None}, "c0"]
            )
        )

    def test_an_error_method_fails(self):
        self.assertFalse(_accepted(["error", {"type": "invalidArguments"}, "c0"]))

    def test_not_created_fails(self):
        self.assertFalse(
            _accepted(
                [
                    "x:Certificate/set",
                    {"notCreated": {"c": {"type": "invalidProperties"}}},
                    "c0",
                ]
            )
        )

    def test_not_updated_fails(self):
        self.assertFalse(
            _accepted(
                [
                    "x:Tracer/set",
                    {"notUpdated": {"t": {"type": "notFound"}}},
                    "c0",
                ]
            )
        )

    def test_a_caller_reading_the_rejection_itself_may_tolerate_it(self):
        self.assertTrue(
            _accepted(
                [
                    "x:Account/set",
                    {"notCreated": {"a": {"type": "alreadyExists"}}},
                    "c0",
                ],
                stalwart_jmap_tolerate_rejected=True,
            )
        )


class TestJmapSecretsStayOffArgv(unittest.TestCase):
    def setUp(self):
        self.task = _call_task()

    def test_command_line_carries_no_credentials_or_body(self):
        cmd = self.task["cmd"]
        self.assertNotIn("-u ", cmd)
        self.assertNotIn("STALWART_ADMIN_PASSWORD", cmd)
        self.assertNotIn("stalwart_jmap_body", cmd)
        self.assertIn("-K -", cmd)

    def test_stdin_config_round_trips_hostile_values(self):
        body = json.dumps({"secret": 'q"\\x', "name": "Zoë"})
        rendered = _render(
            self.task["stdin"],
            STALWART_ADMIN_USER="stalwartadmin",
            STALWART_ADMIN_PASSWORD=PASSWORD,
            stalwart_jmap_body=body,
        )
        config = dict(line.split(" = ", 1) for line in rendered.splitlines())
        self.assertEqual(json.loads(config["user"]), f"stalwartadmin:{PASSWORD}")
        self.assertEqual(json.loads(config["data-binary"]), body)


if __name__ == "__main__":
    unittest.main()
