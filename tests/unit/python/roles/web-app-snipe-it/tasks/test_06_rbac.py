from __future__ import annotations

import copy
import os
import pwd
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-snipe-it"
RBAC_TASKS = ROLE / "tasks/06_rbac.yml"
MCP_MINT_TASKS = ROLE / "tasks/utils/mcp_mint.yml"
DOCKERFILE = ROLE / "files/Dockerfile"
WEB_USER = "SNIPE_IT_WEB_USER"
WEB_USER_REFERENCE = "{{ SNIPE_IT_WEB_USER }}"
BUILD_USER = re.compile(r"^USER (?!root$)(\S+)$", re.MULTILINE)
CONVERGE_EXEC = "container exec {{ SNIPE_IT_CONTAINER_ADDRESS }} sh -c"
CONVERGE_ARGS = "_ {{ SNIPE_IT_WEB_USER | quote }} {{ SNIPE_IT_LDAP_LOG_PATH | quote }}"
CONVERGE_SCRIPT = re.compile(r"sh -c '(.*)' _ ", re.DOTALL)
STACK_HOST_GATE = "IS_STACK_HOST | bool"


def hook_user_problems(tasks: list[dict]) -> list[str]:
    """
    Args:
      tasks: the tasks of tasks/06_rbac.yml.

    Returns:
      One message per registered hook whose rbac_sync_user is not the web user,
      or one message when no task registers a hook.
    """
    hooks = [
        task["vars"] for task in tasks if "rbac_sync_script" in task.get("vars", {})
    ]
    if not hooks:
        return ["no task registers an RBAC hook"]
    return [
        f"the hook runs as {hook['rbac_sync_user']!r}, so snipeit:ldap-sync creates "
        "storage/logs/ldap.log as a user the web process cannot append for"
        for hook in hooks
        if hook["rbac_sync_user"] != WEB_USER_REFERENCE
    ]


def _converge_index(tasks: list[dict]) -> int | None:
    return next(
        (
            index
            for index, task in enumerate(tasks)
            if CONVERGE_EXEC in task.get("ansible.builtin.shell", {}).get("cmd", "")
        ),
        None,
    )


def _hook_index(tasks: list[dict]) -> int | None:
    return next(
        (
            index
            for index, task in enumerate(tasks)
            if "rbac_sync_script" in task.get("vars", {})
        ),
        None,
    )


def ldap_log_converge_problems(tasks: list[dict]) -> list[str]:
    """
    Args:
      tasks: the tasks of tasks/06_rbac.yml.

    Returns:
      Why an ldap.log a root hook left behind would still block the web user's
      sync: no converge step, one after the hook, one off the stack host, one
      that hands the file to another user or reports a change it did not make.
    """
    converge = _converge_index(tasks)
    if converge is None:
        return ["no task hands an existing ldap.log to the web user"]
    task = tasks[converge]
    problems = []
    hook = _hook_index(tasks)
    if hook is None or converge > hook:
        problems.append("the ldap.log owner converges after the hook registers")
    if STACK_HOST_GATE not in str(task.get("when", "")):
        problems.append("the container exec is not gated on the stack host")
    if CONVERGE_ARGS not in task["ansible.builtin.shell"]["cmd"]:
        problems.append("the converge does not hand ldap.log to the web user")
    if task.get("changed_when") != f"{task.get('register')}.stdout | trim == 'changed'":
        problems.append("the converge reports a change it did not make")
    return problems


def _rbac_tasks() -> list[dict]:
    return load_yaml_any(str(RBAC_TASKS), default_if_missing=[])


def _converge_script() -> str:
    task = _rbac_tasks()[_converge_index(_rbac_tasks())]
    return CONVERGE_SCRIPT.search(task["ansible.builtin.shell"]["cmd"]).group(1)


def _run_converge(owner: str, log: Path) -> subprocess.CompletedProcess:
    """
    Args:
      owner: the user the converge must hand the log to.
      log: path of the LDAP log inside the container.

    Returns:
      The finished converge script.
    """
    return subprocess.run(
        ["sh", "-c", _converge_script(), "_", owner, str(log)],
        capture_output=True,
        text=True,
        check=False,
    )


class TestHookUser(unittest.TestCase):
    def test_the_hook_runs_the_ldap_sync_as_the_web_user(self) -> None:
        self.assertEqual([], hook_user_problems(_rbac_tasks()))

    def test_negative_control_the_image_user_is_rejected(self) -> None:
        tasks = copy.deepcopy(_rbac_tasks())
        tasks[_hook_index(tasks)]["vars"]["rbac_sync_user"] = ""
        problems = hook_user_problems(tasks)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("ldap.log", problems[0])

    def test_negative_control_a_file_without_a_hook_is_rejected(self) -> None:
        self.assertEqual(
            ["no task registers an RBAC hook"], hook_user_problems([{"name": "x"}])
        )


class TestLdapLogConverge(unittest.TestCase):
    def test_an_existing_ldap_log_is_handed_to_the_web_user_before_the_hook(
        self,
    ) -> None:
        self.assertEqual([], ldap_log_converge_problems(_rbac_tasks()))

    def test_negative_control_a_converge_after_the_hook_is_rejected(self) -> None:
        tasks = _rbac_tasks()
        reordered = [tasks[_hook_index(tasks)], tasks[_converge_index(tasks)]]
        self.assertEqual(
            ["the ldap.log owner converges after the hook registers"],
            ldap_log_converge_problems(reordered),
        )

    def test_negative_control_an_ungated_converge_is_rejected(self) -> None:
        tasks = copy.deepcopy(_rbac_tasks())
        tasks[_converge_index(tasks)].pop("when")
        self.assertEqual(
            ["the container exec is not gated on the stack host"],
            ldap_log_converge_problems(tasks),
        )

    def test_negative_control_a_missing_converge_is_rejected(self) -> None:
        tasks = _rbac_tasks()
        self.assertEqual(
            ["no task hands an existing ldap.log to the web user"],
            ldap_log_converge_problems([tasks[_hook_index(tasks)]]),
        )

    def test_an_absent_log_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            finished = _run_converge("nobody", Path(directory) / "ldap.log")
        self.assertEqual((0, ""), (finished.returncode, finished.stdout))

    def test_a_log_the_web_user_owns_reports_no_change(self) -> None:
        owner = pwd.getpwuid(os.getuid()).pw_name
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "ldap.log"
            log.touch()
            finished = _run_converge(owner, log)
        self.assertEqual((0, ""), (finished.returncode, finished.stdout))

    def test_negative_control_a_log_another_user_owns_is_chowned(self) -> None:
        stranger = "snipe-it-web-user-that-does-not-exist"
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "ldap.log"
            log.touch()
            finished = _run_converge(stranger, log)
        self.assertNotEqual(0, finished.returncode)
        self.assertIn(stranger, finished.stderr)


class TestWebUser(unittest.TestCase):
    def test_the_web_user_is_the_user_the_image_builds_the_code_as(self) -> None:
        declared = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))[WEB_USER]
        self.assertEqual([declared], BUILD_USER.findall(read_text(str(DOCKERFILE))))

    def test_the_mcp_mint_runs_as_the_same_web_user(self) -> None:
        tasks = load_yaml_any(str(MCP_MINT_TASKS), default_if_missing=[])
        chown = next(
            task["ansible.builtin.command"]["argv"]
            for task in tasks
            if "chown" in task.get("ansible.builtin.command", {}).get("argv", [])
        )
        mint = next(
            task["ansible.builtin.shell"]["cmd"]
            for task in tasks
            if "ansible.builtin.shell" in task
        )
        self.assertIn(f"{WEB_USER_REFERENCE}:root", chown)
        self.assertIn(f"-u {{{{ {WEB_USER} | quote }}}}", mint)


if __name__ == "__main__":
    unittest.main()
