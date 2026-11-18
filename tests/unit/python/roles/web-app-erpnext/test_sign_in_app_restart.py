from __future__ import annotations

import unittest
from typing import Any

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.roles.mapping import ROLE_FILE_VARS_MAIN
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles" / "web-app-erpnext" / "tasks"
APP = "infinito_rbac"
INSTALL = "🛂 Install the sign-in role mapping app and its settings"
RESTART = "🔄 Restart Frappe so all workers load the sign-in app first"
RESTART_FRAPPE = "02_bench_bootstrap/restart_frappe.yml"


def _load(name: str) -> list[dict[str, Any]]:
    return DataLoader().load_from_file(str(TASKS / name), trusted_as_template=True)


def _load_vars() -> dict[str, Any]:
    return DataLoader().load_from_file(
        str(TASKS.parent / ROLE_FILE_VARS_MAIN), trusted_as_template=True
    )


def _render(expression: str, variables: dict[str, Any]) -> Any:
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _holds(when, variables: dict[str, Any]) -> bool:
    """Args:
        when: the task's ``when``, a condition or a list of them.
        variables: the variables the conditions read.

    Returns:
        Whether every condition holds, evaluated up to the first false one.
    """
    templar = Templar(loader=DataLoader(), variables=variables)
    return all(
        templar.template(_trust_as_template("{{ " + condition + " }}"))
        for condition in ([when] if isinstance(when, str) else when)
    )


def _task(tasks: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(task for task in tasks if task.get("name") == name)


def _variables(oidc, ldap, pending=False, stdout="UNCHANGED") -> dict[str, Any]:
    return {
        "ERPNEXT_OIDC_ENABLED": oidc,
        "ERPNEXT_LDAP_ENABLED": ldap,
        "ERPNEXT_LOGIN_RBAC_APP": APP,
        "erpnext_login_rbac_restart_marker": {"stat": {"exists": pending}},
        "erpnext_login_rbac_apply": {
            "changed": stdout != "UNCHANGED",
            "stdout": stdout,
        },
    }


class TestSignInAppRestart(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = _load("01_manager_ops.yml")

    def test_turning_ldap_and_sso_off_converges_the_sign_in_to_off(self) -> None:
        install = _task(self.tasks, INSTALL)
        ldap = next(
            task for task in self.tasks if task.get("include_tasks") == "03_ldap.yml"
        )
        directory_ids = _load_vars()["ERPNEXT_LOGIN_RBAC_SETTINGS"]["directory_ids"]
        sync = _load("04_rbac.yml")[0]["vars"]["rbac_sync_enabled"]

        self.assertNotIn("when", install)
        self.assertEqual(
            install["environment"]["LOGIN_RBAC_SETTINGS_JSON"],
            "{{ ERPNEXT_LOGIN_RBAC_SETTINGS | to_json }}",
        )
        for variant, oidc, ldap_on in (("V3", False, True), ("V2", False, False)):
            with self.subTest(variant=variant):
                variables = _variables(oidc, ldap_on)
                self.assertIs(_render(directory_ids, variables), ldap_on)
                self.assertIs(_holds(ldap["when"], variables), ldap_on)
                self.assertIs(_render(sync, variables), ldap_on)

    def test_a_new_install_or_a_pending_restart_restarts_frappe(self) -> None:
        when = _task(self.tasks, RESTART)["when"]

        for variables, restarts in (
            (_variables(False, True, stdout=f"CHANGED installed {APP}"), True),
            (_variables(True, True, pending=True), True),
            (_variables(True, False, stdout=f"CHANGED settings {APP}"), False),
            (_variables(True, True), False),
        ):
            with self.subTest(variables=variables):
                self.assertIs(_holds(when, variables), restarts)

    def test_a_site_without_sso_or_ldap_still_restarts_for_a_new_install(
        self,
    ) -> None:
        when = _task(self.tasks, RESTART)["when"]

        for pending, restarts in ((True, True), (False, False)):
            with self.subTest(pending=pending):
                variables = _variables(False, False, pending=pending)
                self.assertIs(_holds(when, variables), restarts)

    def test_a_staged_app_keeps_its_restart_pending_until_the_restart_ran(
        self,
    ) -> None:
        touch = next(
            task
            for task in _load("00_core.yml")
            if task.get("ansible.builtin.file", {}).get("state") == "touch"
        )
        restart = _task(self.tasks, RESTART)
        probe = next(task for task in self.tasks if "ansible.builtin.stat" in task)

        for staged in (True, False):
            with self.subTest(staged=staged):
                self.assertIs(
                    _holds(
                        touch["when"], {"erpnext_login_rbac_stage": {"changed": staged}}
                    ),
                    staged,
                )
        self.assertEqual(
            {
                touch["ansible.builtin.file"]["path"],
                probe["ansible.builtin.stat"]["path"],
                restart["block"][-1]["ansible.builtin.file"]["path"],
            },
            {"{{ ERPNEXT_LOGIN_RBAC_RESTART_MARKER }}"},
        )
        self.assertEqual(probe["register"], "erpnext_login_rbac_restart_marker")
        self.assertEqual(
            restart["block"][-1]["ansible.builtin.file"]["state"], "absent"
        )
        self.assertEqual(
            restart["block"][0]["ansible.builtin.include_tasks"], RESTART_FRAPPE
        )
        names = [str(task.get("name")) for task in self.tasks]
        self.assertLess(names.index(probe["name"]), names.index(RESTART))

    def test_every_restart_reaches_each_process_that_loads_the_app_hooks(
        self,
    ) -> None:
        restart = _load(RESTART_FRAPPE)
        compose = next(
            task for task in restart if task.get("when") == "IS_COMPOSE_MODE"
        )
        swarm = next(task for task in restart if task.get("when") == "IS_SWARM_MODE")
        oidc = _task(
            _load("addons/social_login_key.yml"),
            "🔄 Restart Frappe after a Social Login Key change",
        )

        self.assertEqual(oidc["ansible.builtin.include_tasks"], RESTART_FRAPPE)
        for process in ("BACKEND", "SCHEDULER", "QUEUE_SHORT", "QUEUE_LONG"):
            with self.subTest(process=process):
                self.assertIn(
                    f"ERPNEXT_{process}_CONTAINER", compose["ansible.builtin.shell"]
                )
        self.assertLessEqual(
            {"backend", "scheduler", "queue-short", "queue-long"}, set(swarm["loop"])
        )

    def test_the_restart_runs_before_any_sign_in_setting_changes(self) -> None:
        names = [str(task.get("name")) for task in self.tasks]
        includes = [str(task.get("include_tasks")) for task in self.tasks]

        self.assertLess(names.index(INSTALL), names.index(RESTART))
        self.assertLess(
            names.index(RESTART), includes.index("addons/social_login_key.yml")
        )
        self.assertLess(names.index(RESTART), includes.index("03_ldap.yml"))

    def test_the_later_steps_restart_only_for_their_own_change(self) -> None:
        oidc = _task(
            _load("addons/social_login_key.yml"),
            "🔄 Restart Frappe after a Social Login Key change",
        )
        ldap = _load("03_ldap.yml")

        self.assertEqual(
            oidc["when"], "'OIDC_SLK_CHANGED' in erpnext_oidc_apply.stdout"
        )
        self.assertNotIn("restart_frappe.yml", str(ldap))

    def test_the_staged_app_registers_its_change(self) -> None:
        stage = next(task for task in _load("00_core.yml") if "stack_host_copy" in task)

        self.assertEqual(stage["register"], "erpnext_login_rbac_stage")


if __name__ == "__main__":
    unittest.main()
