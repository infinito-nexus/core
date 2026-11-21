from __future__ import annotations

import json
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles" / "web-app-socialhome"
CONVERGE = ROLE / "tasks" / "02_design" / "converge.yml"
URL = "SOCIALHOME_INTERNAL_URL"
CREDENTIALS = (
    "SOCIALHOME_ADMIN_PASSWORD",
    "socialhome_theme_headers",
    "socialhome_theme_token.json",
)


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(CONVERGE), trusted_as_template=True)


def _task(fragment: str) -> dict:
    return next(task for task in _tasks() if fragment in task["name"])


def _answer(status: int, content: dict) -> dict:
    return {
        "rc": 0,
        "stdout": json.dumps({"status": status, "content": json.dumps(content)}),
    }


def _templated(node, **variables):
    return Templar(loader=DataLoader(), variables=variables).template(node)


class TestTheApiIsReachedInsideTheContainerNamespace(unittest.TestCase):
    def test_every_call_runs_in_the_namespace_on_the_hosting_node(self) -> None:
        calls = [task for task in _tasks() if URL in json.dumps(task, default=str)]
        self.assertEqual(5, len(calls))
        for task in calls:
            with self.subTest(task=task["name"]):
                self.assertNotIn("uri_retry", task)
                self.assertNotIn("ansible.builtin.uri", task)
                self.assertEqual(
                    "{{ SOCIALHOME_NETNS_PYTHON }}",
                    task["ansible.builtin.command"]["argv"],
                )
                self.assertIn(URL, task["environment"]["HTTP_URL"])
                self.assertEqual("{{ SOCIALHOME_HOST_NODE }}", task["delegate_to"])
                self.assertIs(True, task["become"])

    def test_the_credentials_ride_only_in_the_masked_stdin_program(self) -> None:
        carriers = [
            task
            for task in _tasks()
            if "ansible.builtin.set_fact" not in task
            and any(marker in json.dumps(task, default=str) for marker in CREDENTIALS)
        ]
        self.assertEqual(4, len(carriers))
        for task in carriers:
            with self.subTest(task=task["name"]):
                command = task.get("ansible.builtin.command", {})
                self.assertIn("http_request_program", str(command.get("stdin", "")))
                rest = {**task, "ansible.builtin.command": {**command, "stdin": ""}}
                for marker in CREDENTIALS:
                    self.assertNotIn(marker, json.dumps(rest, default=str))
                self.assertIn("MASK_CREDENTIALS_IN_LOGS", task["no_log"])


class TestTheAnswersAreRead(unittest.TestCase):
    def test_the_token_becomes_the_bearer_header(self) -> None:
        headers = _task("Keep the administrator headers")["ansible.builtin.set_fact"]
        self.assertEqual(
            {"Authorization": "Bearer t0k"},
            _templated(
                headers["socialhome_theme_headers"],
                socialhome_theme_token=_answer(200, {"token": "t0k"}),
            ),
        )

    def test_the_primary_colour_is_held_in_lower_case(self) -> None:
        fact = _task("Hold the household primary colour")["ansible.builtin.set_fact"]
        self.assertEqual(
            "#a1b2c3",
            _templated(
                fact["socialhome_theme_primary_current"],
                socialhome_theme_answer=_answer(200, {"primary_color": "#A1B2C3"}),
            ),
        )

    def test_the_household_name_is_held(self) -> None:
        fact = _task("Hold the household name")["ansible.builtin.set_fact"]
        self.assertEqual(
            "Home",
            _templated(
                fact["socialhome_name_current"],
                socialhome_instance_config=_answer(200, {"instance_name": "Home"}),
            ),
        )

    def test_a_write_fails_on_any_status_but_200(self) -> None:
        for fragment in ("Write the household primary colour", "Rename the household"):
            task = _task(fragment)
            register = task["register"]
            for status, failed in ((200, False), (403, True)):
                with self.subTest(task=fragment, status=status):
                    self.assertIs(
                        failed,
                        _templated(
                            _trust_as_template(
                                "{{ (" + task["failed_when"] + ") | bool }}"
                            ),
                            **{register: _answer(status, {})},
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
