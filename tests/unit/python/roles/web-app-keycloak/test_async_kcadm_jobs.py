from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, iter_project_files
from utils.cache.yaml import load_yaml_any

TASKS_DIR = str(PROJECT_ROOT / "roles/web-app-keycloak/tasks") + "/"
LOCK_RETRYING_MODULE = "keycloak_kcadm_update"
SET_FACT_MODULES = ("set_fact", "ansible.builtin.set_fact")


def tasks_of(node):
    for task in node or []:
        if not isinstance(task, dict):
            continue
        yield task
        for nested in ("block", "rescue", "always"):
            yield from tasks_of(task.get(nested))


def role_tasks():
    for path in iter_project_files(extensions=(".yml",)):
        if path.startswith(TASKS_DIR):
            for task in tasks_of(load_yaml_any(path)):
                yield path[len(TASKS_DIR) :], task


def async_kcadm_jobs():
    for path, task in role_tasks():
        if "async" in task and "kcadm" in str(task).lower():
            yield f"{path}: {task.get('name')}", task


def reaped_expressions() -> list[str]:
    return [
        str(task["vars"]["async_reap_jobs"])
        for _path, task in role_tasks()
        if "async_reap_jobs" in (task.get("vars") or {})
    ]


def collected_facts() -> dict[str, str]:
    facts: dict[str, str] = {}
    for _path, task in role_tasks():
        for module in SET_FACT_MODULES:
            for name, value in (task.get(module) or {}).items():
                facts[name] = str(value)
    return facts


def names(variable: str, expression: str) -> bool:
    return re.search(rf"\b{re.escape(variable)}\b", expression) is not None


def reaches_a_reap(result: str, facts: dict[str, str], reaped: list[str]) -> bool:
    carriers = [
        result,
        *(fact for fact, source in facts.items() if names(result, source)),
    ]
    return any(
        names(carrier, expression) for carrier in carriers for expression in reaped
    )


class TestAsyncKcadmJobs(unittest.TestCase):
    def test_the_role_runs_kcadm_jobs_async(self):
        self.assertTrue(list(async_kcadm_jobs()))

    def test_every_async_kcadm_job_goes_through_the_lock_retrying_module(self):
        for label, task in async_kcadm_jobs():
            with self.subTest(task=label):
                self.assertIn(
                    LOCK_RETRYING_MODULE,
                    task,
                    "kcadm gives up its config lock to a concurrent kcadm at once; "
                    "only keycloak_kcadm_update repeats such a call, so no other "
                    "kcadm task may run async",
                )

    def test_every_async_kcadm_job_is_registered_for_the_reap(self):
        for label, task in async_kcadm_jobs():
            with self.subTest(task=label):
                self.assertIn(
                    "register",
                    task,
                    "an async job without a register cannot be reaped, so nobody "
                    "sees it fail",
                )

    def test_every_registered_async_kcadm_result_reaches_a_reap(self):
        reaped = reaped_expressions()
        facts = collected_facts()
        for label, task in async_kcadm_jobs():
            with self.subTest(task=label):
                self.assertTrue(
                    reaches_a_reap(task["register"], facts, reaped),
                    f"'{task['register']}' is registered and never handed to "
                    "async_reap_jobs, directly or through a collected list, so the "
                    "reap neither polls the job nor sees it fail",
                )

    def test_a_result_that_is_never_collected_does_not_reach_the_reap(self):
        reaped = ["{{ kc_declared_client_jobs | default([]) }}"]
        self.assertFalse(reaches_a_reap("kc_declared_client", {}, reaped))
        self.assertTrue(
            reaches_a_reap(
                "kc_declared_client",
                {"kc_declared_client_jobs": "{{ [kc_declared_client] }}"},
                reaped,
            )
        )

    def test_a_collected_list_that_no_reap_consumes_does_not_count(self):
        facts = {"kc_declared_client_jobs": "{{ [kc_declared_client] }}"}
        self.assertFalse(reaches_a_reap("kc_declared_client", facts, []))


if __name__ == "__main__":
    unittest.main()
