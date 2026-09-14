from __future__ import annotations

import unittest

from jinja2 import Environment

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles/test-e2e-playwright/tasks/02_run_one.yml"
TASK_NAME = "⏳ Wait until application is ready (any non-error response)"


def until_expression() -> str:
    tasks = load_yaml_any(str(TASKS))
    for task in tasks:
        if task.get("name") == TASK_NAME:
            return task["until"]
    raise AssertionError(f"task {TASK_NAME!r} not found in {TASKS}")


def settles(result: dict) -> bool:
    template = Environment(autoescape=False).from_string(  # noqa: S701 - ansible condition, not markup
        "{{ " + until_expression() + " }}"
    )
    return template.render(_wait_result=result) == "True"


class TestReadinessUntil(unittest.TestCase):
    def test_a_connection_error_keeps_the_gate_waiting(self):
        self.assertFalse(settles({"status": -1}))

    def test_a_missing_status_keeps_the_gate_waiting(self):
        self.assertFalse(settles({}))

    def test_a_served_response_settles_the_gate(self):
        self.assertTrue(settles({"status": 200}))

    def test_a_redirect_settles_the_gate(self):
        self.assertTrue(settles({"status": 302}))

    def test_a_server_error_keeps_the_gate_waiting(self):
        self.assertFalse(settles({"status": 502}))


if __name__ == "__main__":
    unittest.main()
