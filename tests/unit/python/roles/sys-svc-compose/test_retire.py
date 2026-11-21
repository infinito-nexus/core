"""The compose retirement deletes exactly what the container hard repair installed."""

from __future__ import annotations

import unittest
from typing import Any, ClassVar

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

ROLES = PROJECT_ROOT / "roles"
ROLE = ROLES / "sys-svc-compose"
RETIRED_ID = "sys-ctl-rpr-container-hard"
VERSION_SUFFIX = ".1.2.3.infinito.nexus"


def _trust(value: Any) -> Any:
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, list):
        return [_trust(item) for item in value]
    return value


def _trusted(path) -> dict[str, Any]:
    return {key: _trust(value) for key, value in load_yaml_any(str(path)).items()}


def _module(task: dict[str, Any], name: str) -> dict[str, Any]:
    return task[f"ansible.builtin.{name}"]


class TestRetiredTargets(unittest.TestCase):
    variables: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.variables = {
            **_trusted(PROJECT_ROOT / "group_vars" / "all" / "05_paths.yml"),
            **_trusted(ROLES / "sys-service" / ROLE_FILE_VARS_MAIN),
            **_trusted(ROLES / "sys-timer" / ROLE_FILE_VARS_MAIN),
            **_trusted(ROLE / ROLE_FILE_VARS_MAIN),
            "SYS_SERVICE_VERSION_SUFFIX": VERSION_SUFFIX,
            "system_service_id": RETIRED_ID,
            "system_service_timer_service": RETIRED_ID,
        }

    def _render(self, name: str) -> Any:
        templar = Templar(loader=DataLoader(), variables=self.variables)
        return templar.template(trust_as_template("{{ " + name + " }}"))

    def test_the_retired_id_is_the_removed_role(self) -> None:
        self.assertEqual(RETIRED_ID, self._render("COMPOSE_RETIRED_SERVICE_ID"))
        self.assertFalse((ROLES / RETIRED_ID).exists())

    def test_the_retired_units_are_the_hard_repair_timer_and_service(self) -> None:
        self.assertEqual(
            [
                "rpr-container-hard.1.2.3.infinito.nexus.timer",
                "rpr-container-hard.1.2.3.infinito.nexus.service",
            ],
            list(self._render("COMPOSE_RETIRED_UNITS")),
        )

    def test_the_retired_units_are_named_as_sys_service_and_sys_timer_named_them(
        self,
    ) -> None:
        self.assertEqual(
            [self._render("sys_timer_file"), self._render("system_service_name")],
            list(self._render("COMPOSE_RETIRED_UNITS")),
        )

    def test_the_retired_script_dir_is_the_one_sys_service_wrote(self) -> None:
        self.assertEqual(
            "/opt/scripts/systemctl/sys-ctl-rpr-container-hard",
            self._render("COMPOSE_RETIRED_SCRIPT_DIR"),
        )
        self.assertEqual(
            self._render("system_service_script_dir"),
            self._render("COMPOSE_RETIRED_SCRIPT_DIR"),
        )


class TestRetirementTasks(unittest.TestCase):
    tasks: ClassVar[list[dict[str, Any]]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = load_yaml_any(str(ROLE / "tasks" / "retire.yml"))

    def test_every_compose_host_runs_the_retirement_once(self) -> None:
        core = load_yaml_any(str(ROLE / "tasks" / "00_core.yml"))
        main = load_yaml_any(str(ROLE / ROLE_FILE_TASKS_MAIN))
        retire = [task for task in core if task.get("include_tasks") == "retire.yml"]
        self.assertEqual(1, len(retire))
        self.assertNotIn("when", retire[0])
        self.assertEqual(
            {
                "include_tasks": "00_core.yml",
                "when": "run_once_sys_svc_compose is not defined",
            },
            main[0],
        )

    def test_only_the_retired_units_are_looked_up_in_the_system_unit_dir(
        self,
    ) -> None:
        look = self.tasks[0]
        self.assertEqual("{{ COMPOSE_RETIRED_UNITS }}", look["loop"])
        self.assertEqual(
            "{{ [DIR_SYSTEM_SERVICE, compose_retired_unit] | path_join }}",
            _module(look, "stat")["path"],
        )

    def test_a_host_without_the_units_skips_every_change(self) -> None:
        retire = self.tasks[1]
        self.assertEqual("compose_retired_units_present | length > 0", retire["when"])
        self.assertIn(
            "selectattr('stat.exists')",
            retire["vars"]["compose_retired_units_present"],
        )

    def test_only_the_units_found_are_disabled_and_deleted(self) -> None:
        disable, delete, reload = self.tasks[1]["block"]
        self.assertEqual(
            "{{ ['systemctl', 'disable', '--now'] + compose_retired_units_present }}",
            _module(disable, "command")["argv"],
        )
        self.assertEqual("{{ compose_retired_units_present }}", delete["loop"])
        self.assertEqual("absent", _module(delete, "file")["state"])
        self.assertEqual(
            "{{ [DIR_SYSTEM_SERVICE, compose_retired_unit] | path_join }}",
            _module(delete, "file")["path"],
        )
        self.assertIs(True, _module(reload, "systemd")["daemon_reload"])

    def test_the_script_dir_is_deleted(self) -> None:
        script = self.tasks[2]
        self.assertEqual(
            {"path": "{{ COMPOSE_RETIRED_SCRIPT_DIR }}", "state": "absent"},
            _module(script, "file"),
        )


if __name__ == "__main__":
    unittest.main()
