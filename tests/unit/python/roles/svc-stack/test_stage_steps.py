from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

STAGE = "tasks/utils/stack/stage.yml"
CORE = "tasks/00_core.yml"
PRE_UP = {
    "web-app-jitsi": ("01_keycloak_adapter_build.yml",),
    "web-app-mailu": (
        "roles/sys-svc-mail-smtp/tasks/disable.yml",
        "01_swarm_resolve_peer_vips.yml",
    ),
    "web-app-bluesky": ("01_social_app.yml", "02_login_broker.yml", "03_pds.yml"),
}
PRE_UP_NAMES = {
    "web-app-mailu": (
        "✅ Ensure a self-signed placeholder cert exists before stack-up (host)",
    ),
}


def _flat(tasks: list) -> list[dict]:
    found = []
    for task in tasks or []:
        if isinstance(task, dict):
            found.append(task)
            found.extend(_flat(task.get("block")))
    return found


def _tasks(role: str, rel: str) -> list[dict]:
    path = PROJECT_ROOT / "roles" / role / rel
    return _flat(load_yaml_any(str(path), default_if_missing=[]))


def _includes(role: str, rel: str) -> str:
    return " ".join(
        str(task.get("include_tasks") or task.get("ansible.builtin.include_tasks"))
        for task in _tasks(role, rel)
    )


def _names(role: str, rel: str) -> set[str]:
    return {task.get("name", "") for task in _tasks(role, rel)}


class TestStageSteps(unittest.TestCase):
    def test_each_pre_up_step_runs_in_the_stage_and_not_in_the_core(self) -> None:  # nocheck: test.text-presence -- asserts on the include targets of the parsed stage and core task files  # fmt: skip
        for role, steps in PRE_UP.items():
            for step in steps:
                with self.subTest(role=role, step=step):
                    self.assertIn(step, _includes(role, STAGE))
                    self.assertNotIn(step, _includes(role, CORE))

    def test_each_pre_up_task_runs_in_the_stage_and_not_in_the_core(self) -> None:  # nocheck: test.text-presence -- asserts on the task names of the parsed stage and core task files  # fmt: skip
        for role, names in PRE_UP_NAMES.items():
            for name in names:
                with self.subTest(role=role, name=name):
                    self.assertIn(name, _names(role, STAGE))
                    self.assertNotIn(name, _names(role, CORE))


if __name__ == "__main__":
    unittest.main()
