from __future__ import annotations

import unittest
from typing import Any

import jinja2
from ansible.plugins.filter.core import to_bool
from jinja2.nativetypes import NativeEnvironment

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_HANDLERS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

ROLES = PROJECT_ROOT / "roles"
CORE = ROLES / "sys-ctl-mtn-rbac-sync/tasks/00_core.yml"
SYS_SERVICE = ROLES / "sys-service"
TERMINATOR = ROLES / "sys-service-terminator"
UNIT = "mtn-rbac-sync.test.service"
OMIT = "__omit_place_holder__"
INCLUDE_ROLE = ("ansible.builtin.include_role", "include_role")
SWITCHES = (
    "system_service_force_flush_final",
    "system_service_run_once",
    "system_service_force_flush_instant",
    "system_service_suppress_flush",
)


def _tasks(path: Any) -> list[dict]:
    """Args:
        path: a task or handler file.

    Returns:
        Its tasks with the tasks of every block flattened in.
    """
    flat = []
    for task in load_yaml_any(str(path)):
        flat.append(task)
        flat.extend(task.get("block") or [])
    return flat


def _task(path: Any, name: str) -> dict:
    return next(task for task in _tasks(path) if name in task.get("name", ""))


def _sys_service_vars() -> dict:
    """
    Returns:
        The vars the RBAC sync role hands to its sys-service include.
    """
    for task in load_yaml_any(str(CORE)):
        include = next((task[name] for name in INCLUDE_ROLE if name in task), None)
        if isinstance(include, dict) and include.get("name") == "sys-service":
            return task.get("vars") or {}
    raise AssertionError(f"{CORE} includes no sys-service unit")


def _lifecycle(include_vars: dict, debug: bool) -> dict[str, Any]:
    """Args:
        include_vars: the vars of a sys-service include.
        debug: whether the deploy runs with the sys-service debug switch,
            the CI setting.

    Returns:
        Whether the unit starts while sys-service installs it, whether the
        terminator starts it at the end of the play, and how often the
        terminator retries a failed start, all read from the real gates of
        sys-service and sys-service-terminator.
    """
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    environment.filters["bool"] = to_bool
    environment.globals["lookup"] = lambda name, term: debug
    scope: dict[str, Any] = {
        **load_yaml_any(str(SYS_SERVICE / ROLE_FILE_DEFAULTS_MAIN)),
        **load_yaml_any(str(TERMINATOR / ROLE_FILE_DEFAULTS_MAIN)),
        "omit": OMIT,
        "system_service_run_unit": UNIT,
    }
    switches = load_yaml_any(str(SYS_SERVICE / ROLE_FILE_VARS_MAIN))
    scope.update({name: switches[name] for name in SWITCHES})
    scope.update(include_vars)

    def value(expression: Any) -> Any:
        return (
            environment.from_string(expression).render(**scope)
            if isinstance(expression, str)
            else expression
        )

    def holds(condition: str) -> bool:
        return bool(environment.compile_expression(condition)(**scope))

    for name in ("SYS_SERVICE_ALL_ENABLED", "SYS_SERVICE_DEFAULT_STATE", *SWITCHES):
        scope[name] = value(scope[name])

    handlers = SYS_SERVICE / ROLE_FILE_HANDLERS_MAIN
    base = SYS_SERVICE / "tasks/04_base.yml"
    starts_the_unit = _task(handlers, "Set systemctl service state")
    queued = _task(base, "for the end of the play")
    once = _task(base, "once at the end of the play")
    apply = _task(TERMINATOR / "tasks/01_run_one.yml", "Apply state")

    at_install = (
        holds(starts_the_unit["when"]) and scope["SYS_SERVICE_DEFAULT_STATE"] != OMIT
    )
    at_play_end = holds(queued["when"])
    runs_once = at_play_end and holds(once["when"])
    scope["system_service_run_once_list"] = [UNIT] if runs_once else []
    retries = apply["vars"]["system_service_run_retries"]
    return {
        "at_install": at_install,
        "at_play_end": at_play_end,
        "retries": int(value(retries)) if at_play_end else None,
    }


class TestTheFullSyncWaitsForTheRefreshedHooks(unittest.TestCase):
    def test_ci_runs_every_hook_once_at_the_play_end_and_never_at_install(self):
        self.assertEqual(
            _lifecycle(_sys_service_vars(), debug=True),
            {"at_install": False, "at_play_end": True, "retries": 0},
        )

    def test_a_deploy_without_debug_keeps_the_lifecycle_of_every_other_unit(self):
        self.assertEqual(
            _lifecycle(_sys_service_vars(), debug=False),
            _lifecycle({}, debug=False),
        )
        self.assertEqual(
            _lifecycle(_sys_service_vars(), debug=False),
            {"at_install": False, "at_play_end": False, "retries": None},
        )

    def test_negative_control_the_plain_unit_runs_the_stale_hooks_at_install(self):
        self.assertEqual(
            _lifecycle({}, debug=True),
            {"at_install": True, "at_play_end": False, "retries": None},
        )


if __name__ == "__main__":
    unittest.main()
