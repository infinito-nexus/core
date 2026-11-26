from __future__ import annotations

import copy
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
LOGIN_TASKS = ROLE_DIR / "tasks/utils/export_login.yml"
KV_TASKS = PROJECT_ROOT / "roles/web-app-openbao/tasks/utils/kv.yml"
SEMAPHORE_CORE = PROJECT_ROOT / "roles/web-app-semaphore/tasks/00_core.yml"
SEMAPHORE_EXPORT_LOGINS = "utils/workspaces/openbao.yml"
OPENBAO_SERVICES = PROJECT_ROOT / "roles/web-app-openbao" / ROLE_FILE_META_SERVICES
EXPORT_TASK_PY = PROJECT_ROOT / "roles/web-app-semaphore/files/python/export_task.py"
GATES = [
    "KEYCLOAK_ORGANIZATIONS_ENABLED | bool",
    "(groups.get('web-app-openbao') or []) | length > 0",
]
LOGIN = "KEYCLOAK_EXPORT_CLIENT_LOGIN"


def login_findings(task: dict) -> list[str]:
    """
    Args:
        task: the task that hands the export client's login to OpenBao.

    Returns:
        What keeps it from writing that login through the OpenBao key helper,
        only while organizations and an OpenBao host exist.
    """
    findings = []
    if task.get("ansible.builtin.include_role") != {
        "name": "web-app-openbao",
        "tasks_from": "utils/kv.yml",
    }:
        findings.append(f"include is {task.get('ansible.builtin.include_role')}")
    wanted = {
        "openbao_kv_state": "present",
        "openbao_kv_mount": f"{{{{ {LOGIN}.mount }}}}",
        "openbao_kv_path": f"{{{{ {LOGIN}.path }}}}",
        "openbao_kv_data": f"{{{{ {LOGIN}.data }}}}",
    }
    findings.extend(
        f"{name} is {task.get('vars', {}).get(name)!r}"
        for name, value in wanted.items()
        if task.get("vars", {}).get(name) != value
    )
    if task.get("when") != GATES:
        findings.append(f"when is {task.get('when')!r}")
    return findings


def argv_findings(tasks: list[dict]) -> list[str]:
    """
    Args:
        tasks: the tasks of the OpenBao key helper.

    Returns:
        Every task that puts the key's data into its command or logs it.
    """
    findings = [
        f"{task['name']} puts the data into its command"
        for task in tasks
        if "openbao_kv_data" in str(task.get("ansible.builtin.shell", {}).get("cmd"))
    ]
    findings.extend(
        f"{task['name']} logs"
        for task in tasks
        if "ansible.builtin.shell" in task
        and task.get("no_log") != "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"
    )
    return findings


class TestExportLogin(unittest.TestCase):
    def test_the_login_lands_where_the_export_task_reads_it(self) -> None:
        login = ROLE_VARS[LOGIN]
        self.assertEqual(
            (login["mount"], login["path"]), ("platform", "export/keycloak")
        )
        self.assertEqual(
            login["data"],
            {
                "client_id": "{{ KEYCLOAK_EXPORT_CLIENT_ID }}",
                "client_secret": "{{ KEYCLOAK_EXPORT_CLIENT_SECRET }}",
            },
        )
        script = read_text(str(EXPORT_TASK_PY))
        self.assertIn('PLATFORM_MOUNT = "platform"', script)
        self.assertIn('KEYCLOAK_LOGIN_PATH = "export/keycloak"', script)
        self.assertIn("read_all(PLATFORM_MOUNT, KEYCLOAK_LOGIN_PATH)", script)
        for field in login["data"]:
            self.assertIn(f'client["{field}"]', script)

    def test_the_login_is_written_through_the_key_helper_behind_both_gates(
        self,
    ) -> None:
        (task,) = load_yaml_any(str(LOGIN_TASKS))
        self.assertEqual(login_findings(task), [])

    def test_the_check_catches_a_dropped_gate_or_a_foreign_path(self) -> None:
        (task,) = load_yaml_any(str(LOGIN_TASKS))
        for name, change in (
            ("no organizations gate", lambda t: t["when"].pop(0)),
            ("no openbao gate", lambda t: t["when"].pop(1)),
            ("foreign path", lambda t: t["vars"].update(openbao_kv_path="export/x")),
            ("absent", lambda t: t["vars"].update(openbao_kv_state="absent")),
        ):
            with self.subTest(change=name):
                planted = copy.deepcopy(task)
                change(planted)
                self.assertTrue(login_findings(planted))

    def test_the_secret_travels_on_stdin_and_never_reaches_a_log(self) -> None:  # nocheck: test.text-presence -- analyses the parsed kv tasks, negative control below  # fmt: skip
        tasks = load_yaml_any(str(KV_TASKS))
        self.assertEqual(argv_findings(tasks), [])
        write = next(t for t in tasks if t["name"].startswith("🔐 Write"))
        self.assertIn(
            "openbao_kv_data | to_json", write["ansible.builtin.shell"]["stdin"]
        )

    def test_the_argv_check_catches_data_in_the_command(self) -> None:
        tasks = copy.deepcopy(load_yaml_any(str(KV_TASKS)))
        write = next(t for t in tasks if t["name"].startswith("🔐 Write"))
        write["ansible.builtin.shell"]["cmd"] += " {{ openbao_kv_data | to_json }}"
        write["no_log"] = False
        self.assertEqual(len(argv_findings(tasks)), 2)

    def test_the_write_runs_after_openbao_beside_the_other_export_logins(
        self,
    ) -> None:
        run_after = load_yaml_any(str(OPENBAO_SERVICES))["openbao"]["run_after"]
        self.assertIn("web-app-keycloak", run_after)
        calls = [
            (include["when"], task)
            for include in load_yaml_any(str(SEMAPHORE_CORE))
            if include.get("include_tasks") == SEMAPHORE_EXPORT_LOGINS
            for task in load_yaml_any(
                str(SEMAPHORE_CORE.parent / SEMAPHORE_EXPORT_LOGINS)
            )
            if task.get("ansible.builtin.include_role", {}).get("tasks_from")
            == "utils/export_login.yml"
        ]
        self.assertEqual(
            calls,
            [
                (
                    "SEMAPHORE_WORKSPACES_ENABLED | bool",
                    {
                        "name": "🔐 Hand the login of the Keycloak client of the export to OpenBao",
                        "ansible.builtin.include_role": {
                            "name": "web-app-keycloak",
                            "tasks_from": "utils/export_login.yml",
                        },
                        "vars": {"application_id": "web-app-keycloak"},
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
