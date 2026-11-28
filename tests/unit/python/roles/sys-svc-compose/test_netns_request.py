from __future__ import annotations

import json
import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment, nodes

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.templating.ansible import _trust_as_template

HELPER = (
    PROJECT_ROOT / "roles" / "sys-svc-compose" / "tasks" / "utils" / "netns_request.yml"
)
PARAM_RE = re.compile(r"^# Param: (netns_request_\w+)", re.MULTILINE)
LOCALS = {"netns_request_answer", "netns_request_missing", "netns_request_shown_url"}
CALLABLES = {"q", "lookup"}
CONDITIONS = ("when", "until", "changed_when", "failed_when")
NO_LOG = "{{ netns_request_no_log | bool }}"
VALUE_NAMES = re.compile(r"netns_request_(?!missing\b)\w+")


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(HELPER), trusted_as_template=True)


def _task(module: str) -> dict:
    return next(task for task in _tasks() if module in task)


def _params() -> list[str]:
    return PARAM_RE.findall(read_text(str(HELPER)))


def _expressions(node, key=None):
    if isinstance(node, dict):
        for child_key, child in node.items():
            yield from _expressions(child_key, None)
            yield from _expressions(child, child_key)
    elif isinstance(node, list):
        for child in node:
            yield from _expressions(child, key)
    elif isinstance(node, str):
        if key in CONDITIONS or key == "that":
            yield "{{ " + node + " }}"
        elif "{{" in node:
            yield node


def _read_names() -> set[str]:
    environment = Environment(autoescape=True)
    return {
        node.name
        for expression in _expressions(_tasks())
        for node in environment.parse(expression).find_all(nodes.Name)
        if node.ctx == "load"
    }


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _condition(task: dict, key: str, **variables):
    return _render("{{ (" + task[key] + ") | bool }}", **variables)


def _kept(answer: dict) -> dict:
    value = _task("ansible.builtin.set_fact")["ansible.builtin.set_fact"]
    return _render(next(iter(value.values())), netns_request_answer=answer)


def _answer(rc: int, stdout: str, changed: bool) -> dict:
    return {"rc": rc, "stdout": stdout, "changed": changed}


class TestTheInterface(unittest.TestCase):
    def test_every_documented_param_is_read_and_every_read_name_is_documented(
        self,
    ) -> None:
        self.assertEqual(set(_params()), _read_names() - LOCALS - CALLABLES)

    def test_the_assert_names_exactly_the_params_without_a_default(self) -> None:
        text = read_text(str(HELPER))
        optional = {
            name for name in _params() if re.search(rf"{name} \| default\(", text)
        }
        missing = _task("ansible.builtin.assert")["vars"]["netns_request_missing"]
        self.assertEqual(sorted(set(_params()) - optional), sorted(_render(missing)))

    def test_the_assert_reports_only_the_missing_params(self) -> None:
        missing = _task("ansible.builtin.assert")["vars"]["netns_request_missing"]
        given = {
            "netns_request_argv": ["python3", "-"],
            "netns_request_host": "node",
            "netns_request_method": "GET",
            "netns_request_status": [200],
            "netns_request_retries": 0,
            "netns_request_delay": 0,
        }
        self.assertEqual(
            ["netns_request_no_log", "netns_request_result", "netns_request_url"],
            sorted(_render(missing, **given)),
        )

    def test_the_title_shows_the_url_only_unmasked(self) -> None:
        shown = _task("ansible.builtin.command")["vars"]["netns_request_shown_url"]
        for no_log, expected in ((True, "masked URL"), (False, "http://app/x")):
            with self.subTest(no_log=no_log):
                self.assertEqual(
                    expected,
                    _render(
                        shown,
                        netns_request_no_log=no_log,
                        netns_request_url="http://app/x",
                    ),
                )

    def test_the_mask_has_no_default(self) -> None:
        self.assertNotIn("netns_request_no_log | default", read_text(str(HELPER)))

    def test_every_task_that_sees_a_value_sets_its_own_no_log(self) -> None:
        for task in _tasks():
            with self.subTest(task=task["name"]):
                if "ansible.builtin.assert" in task:
                    self.assertNotIn("no_log", task)
                    self.assertEqual(
                        set(),
                        set(
                            VALUE_NAMES.findall(
                                json.dumps(task["ansible.builtin.assert"])
                            )
                        ),
                    )
                else:
                    self.assertEqual(NO_LOG, task["no_log"])


class TestTheResult(unittest.TestCase):
    def test_a_skip_sends_nothing_and_keeps_a_skipped_result(self) -> None:
        command = _task("ansible.builtin.command")
        self.assertIs(False, _condition(command, "when", netns_request_skip=True))
        self.assertIs(True, _condition(command, "when"))
        self.assertNotIn("when", _task("ansible.builtin.set_fact"))
        kept = _kept({"skipped": True, "changed": False})
        self.assertNotIn("status", kept)
        self.assertIs(True, _render("{{ kept is skipped }}", kept=kept))
        self.assertIs(False, _render("{{ kept is changed }}", kept=kept))

    def test_the_answer_lands_next_to_the_command_result(self) -> None:
        answer = json.dumps({"status": 201, "content_type": "json", "content": "{}"})
        kept = _kept(_answer(0, answer, True))
        self.assertEqual(
            (201, "json", "{}"), (kept["status"], kept["content_type"], kept["content"])
        )
        self.assertIs(True, _render("{{ kept is changed }}", kept=kept))
        self.assertIs(False, _render("{{ kept is skipped }}", kept=kept))

    def test_changed_follows_the_changed_statuses(self) -> None:
        command = _task("ansible.builtin.command")
        answer = _answer(0, json.dumps({"status": 201}), False)
        for changed, expected in (([201], True), ([200], False)):
            with self.subTest(changed=changed):
                self.assertIs(
                    expected,
                    _condition(
                        command,
                        "changed_when",
                        netns_request_answer=answer,
                        netns_request_changed=changed,
                    ),
                )
        self.assertIs(
            False, _condition(command, "changed_when", netns_request_answer=answer)
        )

    def test_failed_when_rejects_a_status_outside_the_list(self) -> None:
        command = _task("ansible.builtin.command")
        for status, failed in ((200, False), (503, True)):
            with self.subTest(status=status):
                self.assertIs(
                    failed,
                    _condition(
                        command,
                        "failed_when",
                        netns_request_answer=_answer(
                            0, json.dumps({"status": status}), False
                        ),
                        netns_request_status=[200],
                    ),
                )
        self.assertIs(
            True,
            _condition(
                command,
                "failed_when",
                netns_request_answer=_answer(1, "", False),
                netns_request_status=[200],
            ),
        )

    def test_a_failed_attempt_is_read_without_parsing_its_stdout(self) -> None:
        command = _task("ansible.builtin.command")
        failed = _answer(1, "", False)
        for key in ("until", "changed_when"):
            with self.subTest(key=key):
                self.assertIs(
                    False,
                    _condition(
                        command,
                        key,
                        netns_request_answer=failed,
                        netns_request_status=[200],
                        netns_request_changed=[200],
                    ),
                )


if __name__ == "__main__":
    unittest.main()
