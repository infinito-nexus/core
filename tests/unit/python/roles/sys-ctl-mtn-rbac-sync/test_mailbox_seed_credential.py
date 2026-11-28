import unittest

import jinja2
from jinja2.nativetypes import NativeEnvironment

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/sys-ctl-mtn-rbac-sync"
CORE = load_yaml_any(str(ROLE / "tasks/00_core.yml"))
SEED = load_yaml_any(str(ROLE / "tasks/mailbox.yml"))
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
SEED_FILE = "{{ RBAC_SYNC_MAILBOX_FILE }}"
SEED_TASKS = "mailbox.yml"
INCLUDE_ROLE = ("ansible.builtin.include_role", "include_role")
INCLUDE_TASKS = ("ansible.builtin.include_tasks", "include_tasks")
STAT = ("ansible.builtin.stat", "stat")
COPY = ("ansible.builtin.copy", "copy")


def _module(task, names):
    return next((task[name] for name in names if name in task), None)


def _holds(condition, facts):
    """Args:
        condition: the ``when`` of a task, absent, a string or a list of strings.
        facts: the registered results the condition may read.

    Returns:
        Whether every part of the condition renders true.
    """
    if condition is None:
        return True
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    parts = condition if isinstance(condition, list) else [condition]
    return all(
        bool(environment.from_string("{{ " + part + " }}").render(**facts))
        for part in parts
    )


def _seed_written_before_the_service_starts(seed_exists):
    """Walk tasks/00_core.yml up to the sys-service include that starts the run.

    Args:
        seed_exists: whether ``mailbox.json`` of an earlier deploy is on the host.

    Returns:
        Whether a run of tasks/mailbox.yml that writes the seed precedes the start.
    """
    facts = {}
    for task in CORE:
        include = _module(task, INCLUDE_ROLE)
        if isinstance(include, dict) and include.get("name") == "sys-service":
            return False
        stat = _module(task, STAT)
        if isinstance(stat, dict) and stat.get("path") == SEED_FILE:
            facts[task["register"]] = {"stat": {"exists": seed_exists}}
        if (
            _module(task, INCLUDE_TASKS) == SEED_TASKS
            and (task.get("vars") or {}).get("rbac_sync_mailbox_enabled") is True
            and _holds(task.get("when"), facts)
        ):
            return True
    raise AssertionError("tasks/00_core.yml includes no sys-service unit")


class TestTheSeedBindsWithTheCredentialOfThisDeploy(unittest.TestCase):
    def test_an_applied_seed_takes_the_current_credential_before_the_service_starts(
        self,
    ):
        self.assertTrue(_seed_written_before_the_service_starts(True))

    def test_a_host_without_the_applied_layout_gets_no_seed(self):
        self.assertFalse(_seed_written_before_the_service_starts(False))

    def test_the_seed_tasks_write_the_bind_credential_of_this_deploy(self):
        writes = [
            copy
            for copy in (_module(task, COPY) for task in SEED[0]["block"])
            if isinstance(copy, dict) and copy.get("dest") == SEED_FILE
        ]

        self.assertEqual(len(writes), 1)
        self.assertIn("RBAC_SYNC_MAILBOX ", writes[0]["content"])
        self.assertEqual(
            VARS["RBAC_SYNC_MAILBOX"]["bind_password"], "{{ LDAP.BIND_CREDENTIAL }}"
        )


if __name__ == "__main__":
    unittest.main()
