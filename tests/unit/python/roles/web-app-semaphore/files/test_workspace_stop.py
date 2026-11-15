from __future__ import annotations

import copy
import json
import unittest

import jinja2

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

from ._semaphore_fake import (
    ALIAS,
    FINISHED,
    ROLE,
    WORKSPACE_ID,
    FakeSemaphore,
    load_project,
    load_workspace,
    platform_spec,
    workspace_spec,
)

PLAYBOOK = PROJECT_ROOT / "playbook-workspace.yml"
STOP_TASKS = ROLE / "tasks" / "utils" / "workspace" / "stop.yml"
RESULT_TASKS = ROLE / "tasks" / "utils" / "workspace" / "result.yml"
SEMAPHORE = "web-app-semaphore"
ERASING_FIRST = (
    "web-app-proxmox",
    "svc-virt-incus",
    "web-svc-seaweedfs",
    "web-app-openbao",
)


def load(path):
    return copy.deepcopy(load_yaml_str(read_text(str(path))))


def unfold(tasks):
    for task in tasks:
        yield task
        yield from unfold(task.get("block") or [])


def include(task):
    return task.get("ansible.builtin.include_role") or {}


def runs_on(task, action):
    """Args:
    task: a task of the playbook.
    action: ``apply`` or ``destroy``.

    Returns:
        Whether no ``WORKSPACE_ACTION`` condition of the task excludes ``action``.
    """
    when = task.get("when") or []
    conditions = [when] if isinstance(when, str) else when
    named = [c for c in conditions if c.startswith("WORKSPACE_ACTION == ")]
    return all(c == f"WORKSPACE_ACTION == '{action}'" for c in named)


def operation_steps(playbook, action):
    """Args:
    playbook: the parsed ``playbook-workspace.yml``.
    action: ``apply`` or ``destroy``.

    Returns:
        The steps of the operation in order: ``stop`` for the stop of
        ``web-app-semaphore``, then one role name per role the loop runs.
    """
    play = playbook[0]
    steps = []
    for task in play["tasks"]:
        if not runs_on(task, action):
            continue
        if include(task) == {"name": SEMAPHORE, "tasks_from": "workspace_stop"}:
            steps.append("stop")
        elif include(task).get("tasks_from") == "workspace":
            roles = list(play["vars"]["workspace_roles"])
            reverse = action == "destroy" and "reverse" in task["loop"]
            steps += list(reversed(roles)) if reverse else roles
    return steps


def stop_spec():
    """Returns:
    The spec ``tasks/utils/workspace/stop.yml`` hands ``project.py``, with the
    values of :func:`workspace_spec` under exactly its keys.
    """
    task = next(
        t
        for t in load(STOP_TASKS)
        if "semaphore_workspace_stop_spec" in t.get("vars", {})
    )
    shape = task["vars"]["semaphore_workspace_stop_spec"]
    full = workspace_spec(action="stop")
    return {
        key: (
            {inner: full[key][inner] for inner in value}
            if isinstance(value, dict)
            else full[key]
        )
        for key, value in shape.items()
    }


def erase_findings(mod, api, steps, tasks):
    """Args:
    mod: the converger.
    api: the fake holding ``tasks``.
    steps: :func:`operation_steps` of ``destroy``.
    tasks: the tasks of the workspace that are unfinished before it.

    Returns:
        ``(findings, stopped)``: one finding per role that erases while one of
        ``tasks`` is unfinished, and the sum of the counts the stop and the
        destroy of ``web-app-semaphore`` report.
    """
    findings = []
    stopped = 0
    for step in steps:
        if step == "stop":
            stopped += mod.run_workspace(api, stop_spec(), lambda s: None)[1]["result"][
                "stopped_tasks"
            ]
            continue
        if step == SEMAPHORE:
            spec = workspace_spec(action="destroy")
            stopped += mod.run_workspace(api, spec, lambda s: None)[1]["result"][
                "stopped_tasks"
            ]
            continue
        held = {t["id"]: t["status"] for t in api.tasks}
        findings += [
            f"{step} erases while task {task['id']} is {held[task['id']]}"
            for task in tasks
            if task["id"] in held and held[task["id"]] not in FINISHED
        ]
    return findings, stopped


class WorkspaceStopTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)
        self.mod.converge(self.api, platform_spec(), lambda s: None)
        templates = self.mod.run_workspace(self.api, workspace_spec(), lambda s: None)[
            1
        ]["result"]["templates"]
        provision = templates[f"provision {ALIAS}"]
        deploy = templates["deploy"]
        self.active = [
            self.api.add_task(
                provision["project_id"], provision["template_id"], "waiting"
            ),
            self.api.add_task(deploy["project_id"], deploy["template_id"], "running"),
        ]

    def test_the_destroy_stops_every_task_before_the_first_role_erases(self):
        playbook = load(PLAYBOOK)
        steps = operation_steps(playbook, "destroy")
        self.assertEqual(steps[:2], ["stop", ERASING_FIRST[0]])
        self.assertNotIn("stop", operation_steps(playbook, "apply"))
        self.assertEqual(operation_steps(playbook, "apply")[-1], ERASING_FIRST[0])
        self.assertEqual(stop_spec()["workspace"]["action"], "stop")
        self.assertEqual(
            erase_findings(self.mod, self.api, steps, self.active), ([], 2)
        )

    def test_negative_control_the_stop_after_the_loop_lets_the_roles_erase_first(
        self,
    ):
        playbook = load(PLAYBOOK)
        tasks = playbook[0]["tasks"]
        stop = next(
            t for t in tasks if include(t).get("tasks_from") == "workspace_stop"
        )
        tasks.remove(stop)
        tasks.append(stop)
        findings, _ = erase_findings(
            self.mod, self.api, operation_steps(playbook, "destroy"), self.active
        )
        self.assertEqual(
            findings,
            [
                f"{role} erases while task {task['id']} is {status}"
                for role in ERASING_FIRST
                for task, status in zip(
                    self.active, ("waiting", "running"), strict=True
                )
            ],
        )

    def test_the_result_line_sums_the_stop_and_the_destroy(self):
        write = next(
            t
            for t in unfold(load(RESULT_TASKS))
            if "semaphore_workspace_destroyed" in str(t.get("ansible.builtin.copy"))
        )
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined)  # noqa: S701 - renders an Ansible copy content to JSON, never HTML
        environment.filters["combine"] = lambda left, right: {**left, **right}
        environment.filters["to_json"] = json.dumps
        written = environment.from_string(
            write["ansible.builtin.copy"]["content"]
        ).render(
            semaphore_workspace_destroyed={
                "result": {"workspace": WORKSPACE_ID, "stopped_tasks": 1}
            },
            semaphore_workspace_stopped=2,
        )
        self.assertEqual(
            load_workspace().destroy_result(WORKSPACE_ID, json.loads(written)),
            f'{{"destroyed": true, "stopped_tasks": 3, "workspace": "{WORKSPACE_ID}"}}',
        )


if __name__ == "__main__":
    unittest.main()
