from __future__ import annotations

import unittest
from typing import Any

from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.plugins.filter.mathstuff import FilterModule as MathFilters
from jinja2 import ChainableUndefined
from jinja2.nativetypes import NativeEnvironment

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import ROLE, role_task

CHECK_VAR = "TEST_E2E_PLAYWRIGHT_POST_PASS_CHECK"
CHECK_REF = "{{ " + CHECK_VAR + " }}"
CHECK_PATH = (
    "{{ lookup('path_absolute', 'roles', application_id, "
    "'tasks/utils/playwright_post_pass.yml') }}"
)
STAT = "🔍 Look for a post-pass check"
CHECK = "🧪 Run the post-pass check"
RECORD = "📝 Record the failed post-pass check"
SERIAL_COLLECT = ("03_run_pass.yml", "📝 Report and archive the Playwright run")
PARALLEL_COLLECT = (
    "01_setup/parallel.yml",
    "📝 Report and archive each handed-over run",
)
SERIAL_RUN = ("03_run_pass.yml", "▶️ Run Playwright with the RBAC sync")
TIMED_RUN = ("03_run_pass.yml", "🎬 Time and run the Playwright container")
SYNC_START = "🔁 Start the RBAC sync on its test interval"
SYNC_STOP = "⏹️ Stop the RBAC sync test interval"
CLOCK = "⏱️ Read the stack host clock the pass starts on"
RUN = "▶️ Run Playwright container"
ROLE_ID = "web-svc-logout"


def render(expression: str, **variables: Any) -> Any:
    """Render a task value the way Ansible does, keeping its native type.

    Args:
        expression: the templated value.
        **variables: the variables in scope.

    Returns:
        The rendered value.
    """
    env = NativeEnvironment(undefined=ChainableUndefined)
    env.filters.update(CoreFilters().filters())
    env.filters.update(MathFilters().filters())
    return env.from_string(expression).render(**variables)


def holds(condition: str, **variables: Any) -> bool:
    """Evaluate a ``when`` condition the way Ansible does.

    Args:
        condition: the condition text.
        **variables: the variables in scope.
    """
    return render("{{ (" + condition + ") | bool }}", **variables)


def records_once(expression: str) -> bool:
    """Tell whether a failure record adds the role once, whatever came before.

    Args:
        expression: the value the record task sets ``_playwright_failures`` to.
    """
    cases = (
        ([], [ROLE_ID]),
        ([ROLE_ID], [ROLE_ID]),
        (["web-app-x"], ["web-app-x", ROLE_ID]),
    )
    return all(
        render(expression, _playwright_failures=before, application_id=ROLE_ID) == after
        for before, after in cases
    )


class TestPostPassCheck(unittest.TestCase):
    def test_the_check_is_the_role_file_found_by_its_presence(self) -> None:
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(variables[CHECK_VAR], CHECK_PATH)
        stat = role_task("04_collect.yml", STAT)
        self.assertEqual(stat["ansible.builtin.stat"]["path"], CHECK_REF)
        self.assertEqual((stat["delegate_to"], stat["become"]), ("localhost", False))
        check = role_task("04_collect.yml", CHECK)
        self.assertEqual(check["block"][0]["ansible.builtin.include_tasks"], CHECK_REF)
        found = {"_playwright_post_pass_check": {"stat": {"exists": True}}}
        self.assertTrue(holds(check["when"], **found))
        for registered in ({"stat": {"exists": False}}, {"skipped": True}):
            with self.subTest(registered=registered):
                self.assertFalse(
                    holds(check["when"], _playwright_post_pass_check=registered)
                )

    def test_a_pass_without_a_recorded_start_runs_no_check(self) -> None:
        when = role_task("04_collect.yml", STAT)["when"]
        self.assertFalse(holds(when, _playwright_pass_started=""))
        self.assertTrue(holds(when, _playwright_pass_started="1762970000.5"))

    def test_both_paths_hand_over_the_start_on_the_stack_host_clock(self) -> None:
        serial = role_task(*SERIAL_COLLECT)["vars"]["_playwright_pass_started"]
        clock = {"stdout": "1762970000.123456789"}
        self.assertEqual(
            float(render(serial, _playwright_pass_clock=clock)), float(clock["stdout"])
        )
        parallel = role_task(*PARALLEL_COLLECT)["vars"]["_playwright_pass_started"]
        finished = {"ended_at": 1762970100.5, "seconds": 100.0}
        self.assertEqual(render(parallel, _playwright_run=finished), 1762970000.5)
        unfinished = {
            "stderr": "no result: the scheduler ended before this run finished"
        }
        self.assertEqual(render(parallel, _playwright_run=unfinished), "")
        handed = role_task("04_collect.yml", CHECK)["block"][0]["vars"]
        self.assertEqual(
            render(
                handed["playwright_pass_started"],
                _playwright_pass_started=clock["stdout"],
            ),
            1762970000.123456789,
        )

    def test_the_clock_is_read_on_the_stack_host_right_before_the_run(self) -> None:
        serial, timed = role_task(*SERIAL_RUN), role_task(*TIMED_RUN)
        self.assertEqual(
            serial["block"], [role_task("03_run_pass.yml", SYNC_START), timed]
        )
        self.assertEqual([task["name"] for task in serial["always"]], [SYNC_STOP])
        names = [task["name"] for task in timed["block"]]
        self.assertEqual(names.index(CLOCK) + 1, names.index(RUN))
        clock = role_task("03_run_pass.yml", CLOCK)
        self.assertEqual(clock["ansible.builtin.command"]["argv"], ["date", "+%s.%N"])
        self.assertNotIn("delegate_to", clock)

    def test_a_failed_check_records_the_role_once_and_sets_nothing_else(self) -> None:
        record = role_task("04_collect.yml", RECORD)["ansible.builtin.set_fact"]
        self.assertEqual(list(record), ["_playwright_failures"])
        self.assertTrue(records_once(record["_playwright_failures"]))
        rescue = role_task("04_collect.yml", CHECK)["rescue"]
        self.assertIn(
            "ansible_failed_result.msg", rescue[0]["ansible.builtin.debug"]["msg"]
        )

    def test_a_record_that_appends_again_is_caught(self) -> None:
        self.assertFalse(
            records_once(
                "{{ (_playwright_failures | default([])) + [application_id] }}"
            )
        )


if __name__ == "__main__":
    unittest.main()
