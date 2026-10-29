"""The shared Stalwart JMAP call: what it rejects and what it puts on argv.

A set-level rejection (``notCreated``/``notUpdated``) arrives inside a normal
method response, so checking only for an ``error`` method lets a refused
create pass as success. The admin password and the request body carry
secrets, so neither may reach curl's command line.
"""

from __future__ import annotations

import json
import re
import unittest
from typing import ClassVar

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

TASK = PROJECT_ROOT / "roles" / "web-app-stalwart" / "tasks" / "jmap_call.yml"

PASSWORD = 'p"a\\s$s`w#o[r]d é'

SWARM_ADDRESS = '"$(/usr/bin/resolve-container-id stalwart stalwart)"'

RESOLVED_ONCE = (
    "STALWART_JMAP_URL",
    "STALWART_ADMIN_USER",
    "STALWART_ADMIN_PASSWORD",
)


def _tasks() -> list[dict]:
    return load_yaml_any(str(TASK), default_if_missing=[])


def _module(task: dict, name: str) -> dict:
    return task.get(f"ansible.builtin.{name}") or task.get(name) or {}


def _call_task() -> dict:
    return next(_module(t, "shell") for t in _tasks() if _module(t, "shell"))


def _client_task() -> dict:
    return next(t for t in _tasks() if "stalwart_jmap_client" in _module(t, "set_fact"))


def _resolved_client(**variables) -> dict:
    client = _module(_client_task(), "set_fact")["stalwart_jmap_client"]
    return {key: _render(raw, **variables) for key, raw in client.items()}


def _assert_task() -> dict:
    return next(t for t in _tasks() if _module(t, "assert"))


def _render(template: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _assert_vars(responses: list, **extra) -> dict:
    task = _assert_task()
    variables = {"stalwart_jmap": {"methodResponses": responses}, **extra}
    for name, raw in (task.get("vars") or {}).items():
        variables[name] = _render(raw, **variables)
    return variables


def _batch_accepted(responses: list, **extra) -> bool:
    variables = _assert_vars(responses, **extra)
    that = _module(_assert_task(), "assert")["that"]
    return all(
        _render("{{ (" + expr + ") | bool }}", **variables)
        for expr in ([that] if isinstance(that, str) else that)
    )


def _accepted(response: list, **extra) -> bool:
    return _batch_accepted([response], **extra)


def _retry_done(rc: int, responses: list) -> bool:
    task = next(t for t in _tasks() if _module(t, "shell"))
    return _render(
        "{{ (" + task["until"] + ") | bool }}",
        stalwart_jmap_raw={
            "rc": rc,
            "stdout": json.dumps({"methodResponses": responses}),
        },
        STALWART_JMAP_TRANSIENT_ERRORS=["serverUnavailable", "rateLimit"],
    )


class TestJmapRejectionIsAFailure(unittest.TestCase):
    def test_a_clean_set_passes(self):
        self.assertTrue(
            _accepted(["x:Domain/set", {"created": {"d": {"id": "1"}}}, "c0"])
        )

    def test_null_rejection_maps_pass(self):
        self.assertTrue(
            _accepted(["x:Domain/set", {"notCreated": None, "notUpdated": None}, "c0"])
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


class TestJmapBatchNamesTheRefusedOwner(unittest.TestCase):
    GET: ClassVar[list] = ["x:AppPassword/get", {"list": []}, "contact@infinito.test"]

    def test_a_clean_batch_passes(self):
        self.assertTrue(
            _batch_accepted(
                [self.GET, ["x:AppPassword/get", {"list": []}, "bounce@infinito.test"]]
            )
        )

    def test_an_error_in_a_later_call_fails(self):
        self.assertFalse(
            _batch_accepted(
                [self.GET, ["error", {"type": "forbidden"}, "bounce@infinito.test"]]
            )
        )

    def test_a_later_rejection_fails_and_names_its_call(self):
        responses = [
            self.GET,
            [
                "x:AppPassword/set",
                {"notCreated": {"p": {"type": "overQuota"}}},
                "bounce@infinito.test",
            ],
        ]
        self.assertFalse(_batch_accepted(responses))
        self.assertEqual(
            _assert_vars(responses)["stalwart_jmap_refused"],
            {
                "bounce@infinito.test": {
                    "x:AppPassword/set": {"p": {"type": "overQuota"}}
                }
            },
        )

    def test_a_tolerated_rejection_still_fails_on_an_error(self):
        self.assertFalse(
            _batch_accepted(
                [
                    ["x:Account/set", {"notCreated": {"u0": {"type": "x"}}}, "c0"],
                    ["error", {"type": "invalidArguments"}, "c1"],
                ],
                stalwart_jmap_tolerate_rejected=True,
            )
        )

    def test_a_destroy_of_an_absent_object_passes(self):
        self.assertTrue(
            _batch_accepted(
                [
                    [
                        "x:AppPassword/set",
                        {"notDestroyed": {"3": {"type": "notFound"}}},
                        "bounce@infinito.test",
                    ]
                ]
            )
        )


class TestJmapRetryCoversEveryCall(unittest.TestCase):
    OK: ClassVar[list] = ["x:AppPassword/get", {"list": []}, "a"]

    def test_a_clean_batch_ends_the_retry(self):
        self.assertTrue(_retry_done(0, [self.OK, self.OK]))

    def test_a_transient_error_in_a_later_call_retries(self):
        self.assertFalse(
            _retry_done(0, [self.OK, ["error", {"type": "serverUnavailable"}, "b"]])
        )

    def test_a_permanent_error_ends_the_retry(self):
        self.assertTrue(_retry_done(0, [["error", {"type": "forbidden"}, "a"]]))

    def test_a_failed_transfer_retries(self):
        self.assertFalse(_retry_done(22, []))


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
        client = _resolved_client(
            STALWART_JMAP_URL="http://localhost:8080/jmap/",
            STALWART_ADMIN_USER="stalwartadmin",
            STALWART_ADMIN_PASSWORD=PASSWORD,
        )
        rendered = _render(
            self.task["stdin"], stalwart_jmap_client=client, stalwart_jmap_body=body
        )
        config = dict(line.split(" = ", 1) for line in rendered.splitlines())
        self.assertEqual(json.loads(config["user"]), f"stalwartadmin:{PASSWORD}")
        self.assertEqual(json.loads(config["data-binary"]), body)


class TestJmapClientResolvedOncePerRun(unittest.TestCase):
    def setUp(self):
        self.call = _call_task()
        self.resolve = _client_task()

    def test_the_call_templates_no_resolved_once_variable(self):
        for field in ("cmd", "stdin"):
            for name in RESOLVED_ONCE:
                self.assertNotIn(name, self.call[field])

    def test_the_client_carries_every_resolved_once_variable(self):
        client = _module(self.resolve, "set_fact")["stalwart_jmap_client"]
        for name in RESOLVED_ONCE:
            self.assertTrue(any(name in raw for raw in client.values()), name)

    def test_the_call_reads_only_keys_the_client_sets(self):
        client = _module(self.resolve, "set_fact")["stalwart_jmap_client"]
        used = set(
            re.findall(
                r"stalwart_jmap_client\.(\w+)", self.call["cmd"] + self.call["stdin"]
            )
        )
        self.assertTrue(used)
        self.assertLessEqual(used, set(client))

    def test_the_client_resolves_only_while_undefined(self):
        condition = "{{ (" + str(self.resolve.get("when", True)) + ") | bool }}"
        self.assertTrue(_render(condition))
        self.assertFalse(_render(condition, stalwart_jmap_client={"url": "u"}))

    def test_the_client_resolution_is_masked(self):
        self.assertEqual(
            self.resolve["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"
        )

    def test_a_swarm_address_reaches_the_shell_unresolved(self):
        client = _resolved_client(
            STALWART_JMAP_URL="http://localhost:8080/jmap/",
            STALWART_ADMIN_USER="stalwartadmin",
            STALWART_ADMIN_PASSWORD=PASSWORD,
        )
        cmd = _render(
            self.call["cmd"],
            STALWART_CONTAINER_ADDRESS=SWARM_ADDRESS,
            stalwart_jmap_client=client,
        )
        self.assertTrue(cmd.startswith(f"container exec -i {SWARM_ADDRESS} curl "))
        self.assertTrue(cmd.endswith(" http://localhost:8080/jmap/"))


if __name__ == "__main__":
    unittest.main()
