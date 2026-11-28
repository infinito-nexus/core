from __future__ import annotations

import unittest

from ansible.plugins.filter.core import combine
from jinja2 import Environment, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
STORE_DIR = PROJECT_ROOT / "roles/sys-token-store/tasks"
INIT_TASKS = load_yaml_any(str(ROLE_DIR / "tasks/01_init.yml"))
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
WRITE = load_yaml_any(str(STORE_DIR / "write.yml"))
WRITE_MANY = load_yaml_any(str(STORE_DIR / "write_many.yml"))
HAND_OVER = load_yaml_any(str(STORE_DIR / "utils/hand_over.yml"))
GENERAL_VARS = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/00_general.yml"))
PLATFORM_ADMIN = GENERAL_VARS["IAM_PLATFORM_ADMIN_USER_KEY"]
LEGACY_SLOT = ROLE_VARS["OPENBAO_RECOVERY_LEGACY_SLOT"]
MERGED = "sys_token_store_users_merged"
MASK = "MASK_CREDENTIALS_IN_LOGS"
APP = "web-app-openbao-recovery"
KEY = "recovery-key"


def environment() -> Environment:
    return Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )


def render(text: str, **values) -> str:
    return environment().from_string(text).render(values)


def holds(conditions: list[str], **values) -> bool:
    return all(
        environment().compile_expression(condition)(**values)
        for condition in conditions
    )


def includes(task: dict, tasks_from: str) -> bool:
    role = task.get("ansible.builtin.include_role", {})
    return (
        role.get("name") == "sys-token-store" and role.get("tasks_from") == tasks_from
    )


def conditions(task: dict) -> list[str]:
    own = task.get("when", [])
    return [own] if isinstance(own, str) else list(own)


def index_of(tasks: list[dict], predicate) -> int:
    return next(i for i, task in enumerate(tasks) if predicate(task))


def is_copy(task: dict) -> bool:
    return includes(task, "write.yml") and "OPENBAO_RECOVERY_KEY_LEGACY" in str(
        task.get("vars", {}).get("sys_token_store_token", "")
    )


def is_recovery(task: dict) -> bool:
    return "openbao_approle_login_recovered" in str(task.get("block"))


def copy_task() -> dict:
    return INIT_TASKS[index_of(INIT_TASKS, is_copy)]


def rebuild_task() -> dict:
    block = INIT_TASKS[index_of(INIT_TASKS, is_recovery)]["block"]
    return next(task for task in block if "utils/recover.yml" in str(task))


def copies_between_load_and_recovery(tasks: list[dict]) -> bool:
    """Args:
        tasks: top-level tasks of 01_init.yml.

    Returns:
        Whether the copy sits after the first store load and before the block
        that rebuilds the AppRole.
    """
    load = index_of(tasks, lambda task: includes(task, "01_load.yml"))
    return load < index_of(tasks, is_copy) < index_of(tasks, is_recovery)


def recovery_keys(users: dict) -> dict[str, str]:
    """Args:
        users: the sys_token_store_users mapping the play holds.

    Returns:
        The current and the legacy recovery key as vars/main.yml resolves them.
    """
    context = {
        "sys_token_store_users": users,
        "IAM_PLATFORM_ADMIN_USER_KEY": PLATFORM_ADMIN,
        "OPENBAO_RECOVERY_LEGACY_SLOT": LEGACY_SLOT,
        "OPENBAO_RECOVERY_TOKEN_APP": APP,
    }
    return {
        name: render(ROLE_VARS[name], **context)
        for name in ("OPENBAO_RECOVERY_KEY", "OPENBAO_RECOVERY_KEY_LEGACY")
    }


def copies(users: dict) -> bool:
    return holds(conditions(copy_task()), **recovery_keys(users))


def rebuilds(users: dict) -> bool:
    return holds(
        conditions(rebuild_task()),
        openbao_approle_login_previous={"rc": 1},
        **recovery_keys(users),
    )


def written(users: dict) -> dict:
    """Args:
        users: the store before the copy.

    Returns:
        The store write_many.yml merges from the entry write.yml builds out of
        the copy's vars, rendered from the role files themselves.
    """
    copy_vars = {
        name: render(
            value,
            IAM_PLATFORM_ADMIN_USER_KEY=PLATFORM_ADMIN,
            OPENBAO_RECOVERY_TOKEN_APP=APP,
            **recovery_keys(users),
        )
        for name, value in copy_task()["vars"].items()
    }
    entries = [
        {field: render(value, **copy_vars) for field, value in entry.items()}
        for entry in WRITE[0]["vars"]["sys_token_store_entries"]
    ]
    merge = next(
        task
        for task in WRITE_MANY
        if MERGED in task.get("ansible.builtin.set_fact", {})
    )
    native = NativeEnvironment(undefined=StrictUndefined)
    native.filters["combine"] = combine
    return native.from_string(merge["ansible.builtin.set_fact"][MERGED]).render(
        sys_token_store_users=users, sys_token_store_entries=entries
    )


def unmasked(tasks: list[dict]) -> list[str]:
    """Args:
        tasks: the tasks of write_many.yml.

    Returns:
        The tasks that hold the merged store, with its tokens, without a
        ``no_log`` of their own; the include's ``no_log`` does not reach them.
    """
    found = []
    for task in tasks:
        if "block" in task:
            found.extend(unmasked(task["block"]))
            continue
        include = task.get("ansible.builtin.include_tasks", {})
        own = str(task.get("no_log", "")) + str(
            include.get("apply", {}).get("no_log", "")
            if isinstance(include, dict)
            else ""
        )
        if MERGED in str(task) and MASK not in own:
            found.append(task["name"])
    return found


class TestRecoveryKeyCopy(unittest.TestCase):
    def test_the_copy_runs_between_the_store_load_and_the_approle_rebuild(self):
        self.assertTrue(copies_between_load_and_recovery(INIT_TASKS))

    def test_a_copy_after_the_rebuild_is_caught(self):
        index = index_of(INIT_TASKS, is_copy)
        late = INIT_TASKS[:index] + INIT_TASKS[index + 1 :] + [INIT_TASKS[index]]
        self.assertFalse(copies_between_load_and_recovery(late))

    def test_a_key_only_in_the_legacy_slot_is_copied_and_stays_there(self):
        users = {LEGACY_SLOT: {"tokens": {APP: KEY}}}
        self.assertTrue(copies(users))
        self.assertEqual(
            {"OPENBAO_RECOVERY_KEY": KEY, "OPENBAO_RECOVERY_KEY_LEGACY": KEY},
            recovery_keys(written(users)),
        )

    def test_the_rebuild_reads_the_copied_key_and_stays_shut_without_it(self):
        users = {LEGACY_SLOT: {"tokens": {APP: KEY}}}
        self.assertFalse(rebuilds(users))
        self.assertTrue(rebuilds(written(users)))

    def test_the_hand_over_gives_the_rebuild_the_merged_store(self):
        self.assertEqual(
            HAND_OVER[-1]["ansible.builtin.set_fact"]["sys_token_store_users"],
            "{{ " + MERGED + " }}",
        )

    def test_a_copied_key_is_not_copied_again(self):
        users = {
            LEGACY_SLOT: {"tokens": {APP: KEY}},
            PLATFORM_ADMIN: {"tokens": {APP: KEY}},
        }
        self.assertFalse(copies(users))

    def test_a_deployment_without_a_legacy_key_copies_nothing(self):
        for users in ({}, {PLATFORM_ADMIN: {"tokens": {APP: KEY}}}):
            with self.subTest(users=sorted(users)):
                self.assertFalse(copies(users))

    def test_the_copy_writes_the_platform_administrator_slot_without_logging(self):
        task = copy_task()
        self.assertIn(
            "IAM_PLATFORM_ADMIN_USER_KEY", task["vars"]["sys_token_store_user_key"]
        )
        self.assertIn("OPENBAO_RECOVERY_TOKEN_APP", task["vars"]["sys_token_store_app"])
        self.assertIn(MASK, task["no_log"])

    def test_every_store_task_masks_the_tokens_itself(self):
        self.assertEqual(unmasked(WRITE_MANY), [])

    def test_control_a_store_task_without_its_own_no_log_is_caught(self):
        planted = [*WRITE_MANY, {"name": "leak", "debug": {"var": MERGED}}]
        self.assertEqual(unmasked(planted), ["leak"])

    def test_the_legacy_slot_is_named_without_the_host_account_key(self):
        self.assertNotIn(
            "IAM_HOST_ADMIN_USER_KEY", ROLE_VARS["OPENBAO_RECOVERY_KEY_LEGACY"]
        )
        self.assertIn(
            "OPENBAO_RECOVERY_LEGACY_SLOT", ROLE_VARS["OPENBAO_RECOVERY_KEY_LEGACY"]
        )


if __name__ == "__main__":
    unittest.main()
