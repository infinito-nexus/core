from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, iter_project_files
from utils.cache.yaml import load_yaml_any

TASKS_DIR = str(PROJECT_ROOT / "roles/web-app-keycloak/tasks") + "/"
LOCK_RETRYING_MODULE = "keycloak_kcadm_update"


def tasks_of(node):
    for task in node or []:
        if not isinstance(task, dict):
            continue
        yield task
        for nested in ("block", "rescue", "always"):
            yield from tasks_of(task.get(nested))


def async_kcadm_jobs():
    for path in iter_project_files(extensions=(".yml",)):
        if not path.startswith(TASKS_DIR):
            continue
        for task in tasks_of(load_yaml_any(path)):
            if "async" in task and "kcadm" in str(task).lower():
                yield f"{path[len(TASKS_DIR) :]}: {task.get('name')}", task


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


if __name__ == "__main__":
    unittest.main()
