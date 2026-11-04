import copy
import unittest
from typing import Any, ClassVar

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
from jinja2.nativetypes import NativeEnvironment

from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT, ROLE_DIR

ROLE = ROLE_DIR.name
CONSTRUCTOR = PROJECT_ROOT / "tasks" / "stages" / "01_constructor.yml"
MODES = PROJECT_ROOT / "group_vars" / "all" / "01_modes.yml"
CLI_CHECKS = frozenset({"inventory"})
HOST_CHECKS = ("kernel", "clock")
DOCKER_CHECKS = ("networks", "containers", "volumes", "pools", "ports")
BARE_HOST = {
    "DOCKER_IN_CONTAINER": False,
    "preflight_container_cli": {"stat": {"exists": True}},
}


def _conditions(task: dict[str, Any]) -> list[str]:
    when = task.get("when", [])
    return when if isinstance(when, list) else [when]


def _holds(variables: dict[str, Any], task: dict[str, Any]) -> bool:
    templar = Templar(loader=DataLoader(), variables=variables)
    return all(
        templar.evaluate_conditional(trust_as_template(condition))
        for condition in _conditions(task)
    )


class TestCheckSwitches(unittest.TestCase):
    services: ClassVar[dict[str, Any]]
    tasks: ClassVar[list[dict[str, Any]]]

    @classmethod
    def setUpClass(cls):
        cls.services = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
        cls.tasks = load_yaml_any(str(ROLE_DIR / ROLE_FILE_TASKS_MAIN))

    def _switches(self, **enabled_by_check: bool) -> Any:
        services = copy.deepcopy(self.services)
        for check, enabled in enabled_by_check.items():
            services[entity_name(ROLE)]["checks"][check]["enabled"] = enabled
        applications = {ROLE: {"services": services}}

        def lookup(name: str, role: str, path: str) -> Any:
            self.assertEqual(name, "config")
            node = applications[role]
            for key in path.split("."):
                node = node[key]
            return node

        source = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        return (
            NativeEnvironment()
            .from_string(source["SYS_PREFLIGHT_CHECKS"])
            .render(lookup=lookup)
        )

    def _included(self, checks: Any, **host: Any) -> list[str]:
        variables = {**BARE_HOST, **host, "SYS_PREFLIGHT_CHECKS": checks}
        return [
            task["ansible.builtin.include_tasks"].removesuffix(".yml")
            for task in self.tasks
            if "ansible.builtin.include_tasks" in task and _holds(variables, task)
        ]

    def _role_checks(self) -> list[str]:
        declared = self.services[entity_name(ROLE)]["checks"]
        return [check for check in declared if check not in CLI_CHECKS]

    def test_every_check_runs_with_the_shipped_switches(self):
        self.assertEqual(
            sorted(self._included(self._switches())), sorted(self._role_checks())
        )

    def test_each_switch_turns_off_its_check_alone(self):
        everything = self._role_checks()
        for check in everything:
            with self.subTest(check=check):
                self.assertEqual(
                    sorted(self._included(self._switches(**{check: False}))),
                    sorted(set(everything) - {check}),
                )

    def test_a_host_inside_a_container_skips_the_kernel_and_the_clock(self):
        included = self._included(self._switches(), DOCKER_IN_CONTAINER=True)
        self.assertEqual(
            sorted(included), sorted(set(self._role_checks()) - set(HOST_CHECKS))
        )

    def test_a_host_without_docker_skips_the_docker_checks(self):
        included = self._included(
            self._switches(), preflight_container_cli={"stat": {"exists": False}}
        )
        self.assertEqual(
            sorted(included), sorted(set(self._role_checks()) - set(DOCKER_CHECKS))
        )


class TestAssertGate(unittest.TestCase):
    include: ClassVar[dict[str, Any]]
    modes: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls):
        cls.include = next(
            task
            for task in load_yaml_any(str(CONSTRUCTOR))
            if (task.get("ansible.builtin.include_role") or {}).get("name") == ROLE
        )
        cls.modes = {
            key: trust_as_template(value) if isinstance(value, str) else value
            for key, value in load_yaml_any(str(MODES)).items()
        }

    def test_without_validate_the_role_follows_debug(self):
        self.assertFalse(_holds({**self.modes, "DEBUG": False}, self.include))
        self.assertTrue(_holds({**self.modes, "DEBUG": True}, self.include))

    def test_validate_false_skips_the_role(self):
        self.assertFalse(
            _holds({**self.modes, "DEBUG": True, "VALIDATE": False}, self.include)
        )

    def test_validate_true_runs_the_role(self):
        self.assertTrue(
            _holds({**self.modes, "DEBUG": False, "VALIDATE": True}, self.include)
        )


if __name__ == "__main__":
    unittest.main()
