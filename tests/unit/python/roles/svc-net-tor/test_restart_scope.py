from __future__ import annotations

import sys
import unittest
from unittest import mock

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT
from .test_egress_route import _evaluate

CORE = PROJECT_ROOT / "roles/svc-net-tor/tasks/00_core.yml"
VARS = load_yaml_any(str(PROJECT_ROOT / "roles/svc-net-tor" / ROLE_FILE_VARS_MAIN))
NODES = ("manager-1", "manager-2", "worker-1")
BEFORE = {node: f"{node}-task-1" for node in NODES}
FRESH = {node: f"{node}-task-2" for node in NODES}
MARKERS = {
    "compose": "--force-recreate",
    "forced": "service update --force",
    "nodes": "container stop",
}
NOTHING = {"compose": False, "forced": False, "nodes": []}


def _conditions(task: dict) -> list:
    when = task.get("when", [])
    return list(when) if isinstance(when, list) else [when]


def _flatten(tasks: list[dict], inherited: list) -> list[dict]:
    """
    Args:
        tasks: a task list of 00_core.yml or the ``block`` of one of its tasks.
        inherited: the ``when`` conditions of the blocks around ``tasks``.

    Returns:
        Every task that is no block, in file order, its ``when`` holding the
        conditions of the blocks around it ahead of its own.
    """
    flat: list[dict] = []
    for task in tasks:
        conditions = inherited + _conditions(task)
        if "block" in task:
            flat += _flatten(task["block"], conditions)
        else:
            flat.append({**task, "when": conditions} if conditions else task)
    return flat


def _tasks() -> list[dict]:
    return _flatten(load_yaml_any(str(CORE)), [])


def _text(task: dict) -> str:
    for key in ("ansible.builtin.shell", "ansible.builtin.command"):
        if key in task:
            return str(task[key])
    return ""


def _registering(name: str) -> dict:
    found = [task for task in _tasks() if task.get("register") == name]
    if len(found) != 1:
        raise AssertionError(f"00_core.yml registers {name} {len(found)} times")
    return found[0]


def _runs(task: dict, variables: dict) -> bool:
    when = task.get("when", [])
    return all(
        _evaluate(str(condition), variables, conditional=True)
        for condition in (when if isinstance(when, list) else [when])
    )


def walk(
    swarm: bool = True,
    torrc: tuple[str, ...] = (),
    keys: bool = False,
    after: dict[str, str] | None = None,
) -> tuple[dict, int]:
    """
    Args:
        swarm: deploy in swarm mode, else in compose mode on the first node alone.
        torrc: the nodes whose torrc render reported a change.
        keys: whether the hidden-service key install reported a change.
        after: the task id each node runs once the deploy is done, BEFORE when None.

    Returns:
        The restart paths the role's tasks take after the deploy (the compose
        recreate, the forced update of the whole service and the nodes restarted
        one by one) and the item count the per-node loop expands.
    """
    nodes = NODES if swarm else NODES[:1]
    before = [BEFORE[node] for node in nodes]
    running = after or BEFORE
    variables = {
        "IS_SWARM_MODE": swarm,
        "IS_COMPOSE_MODE": not swarm,
        "IS_STACK_HOST": True,
        "STACK_HOST": nodes[0],
        "_tor_running_before": {
            "changed": False,
            "rc": 0,
            "stdout": "\n".join(before),
            "stdout_lines": before,
        },
        "_tor_hs_keys": {"changed": keys},
        "_tor_torrc": {
            "changed": bool(torrc),
            "results": [{"tor_node": n, "changed": n in torrc} for n in nodes],
        },
        "_tor_running_after": {
            "changed": False,
            "results": [{"tor_node": n, "stdout": running.get(n, "")} for n in nodes],
        },
    }
    variables["TOR_RESTART_REQUIRED"] = _evaluate(
        VARS["TOR_RESTART_REQUIRED"], variables, conditional=False
    )
    taken = {"compose": False, "forced": False, "nodes": []}
    loop_items = 0
    tasks = _tasks()
    start = next(
        index
        for index, task in enumerate(tasks)
        if (task.get("include_role") or {}).get("name") == "sys-svc-compose"
    )
    for task in tasks[start + 1 :]:
        facts = task.get("ansible.builtin.set_fact")
        kind = next((k for k, mark in MARKERS.items() if mark in _text(task)), None)
        if kind == "nodes":
            loop_items = len(_evaluate(task["loop"], variables, conditional=False))
        if (facts is None and kind is None) or not _runs(task, variables):
            continue
        if facts is not None:
            scope = {
                **variables,
                **{
                    name: _evaluate(value, variables, conditional=False)
                    for name, value in (task.get("vars") or {}).items()
                },
            }
            variables.update(
                {
                    name: _evaluate(value, scope, conditional=False)
                    for name, value in facts.items()
                }
            )
        elif kind == "nodes":
            loop_var = task["loop_control"]["loop_var"]
            taken["nodes"] += [
                _evaluate(
                    task["delegate_to"],
                    {**variables, loop_var: item},
                    conditional=False,
                )
                for item in _evaluate(task["loop"], variables, conditional=False)
            ]
        else:
            taken[kind] = True
    return taken, loop_items


def restarts(**scenario) -> dict:
    """
    Args:
        scenario: the keyword arguments of :func:`walk`.

    Returns:
        The restart paths the role's tasks take after the deploy.
    """
    return walk(**scenario)[0]


def expanded(**scenario) -> int:
    """
    Args:
        scenario: the keyword arguments of :func:`walk`.

    Returns:
        The items the per-node restart loop expands before any ``when`` runs,
        the stage at which Ansible already templates ``delegate_to``.
    """
    return walk(**scenario)[1]


class TestRestartScope(unittest.TestCase):
    def test_a_key_change_rolls_the_stack_host_alone(self) -> None:
        self.assertEqual(restarts(keys=True), {**NOTHING, "nodes": ["manager-1"]})

    def test_a_torrc_change_rolls_only_the_node_it_belongs_to(self) -> None:
        self.assertEqual(
            restarts(torrc=("worker-1",)), {**NOTHING, "nodes": ["worker-1"]}
        )

    def test_a_change_on_every_node_rolls_the_whole_service(self) -> None:
        self.assertEqual(restarts(torrc=NODES), {**NOTHING, "forced": True})

    def test_a_deploy_that_recreated_tor_skips_the_restart(self) -> None:
        self.assertEqual(restarts(torrc=NODES, keys=True, after=FRESH), NOTHING)

    def test_a_node_whose_task_the_deploy_replaced_is_left_alone(self) -> None:
        after = {**BEFORE, "worker-1": FRESH["worker-1"]}
        self.assertEqual(restarts(torrc=("worker-1",), after=after), NOTHING)

    def test_compose_recreates_a_container_the_deploy_kept(self) -> None:
        self.assertEqual(
            restarts(swarm=False, torrc=("manager-1",)), {**NOTHING, "compose": True}
        )

    def test_compose_skips_a_container_the_deploy_recreated(self) -> None:
        self.assertEqual(
            restarts(swarm=False, torrc=("manager-1",), after=FRESH), NOTHING
        )

    def test_an_unchanged_config_restarts_nothing(self) -> None:
        self.assertEqual(restarts(), NOTHING)

    def test_the_node_loop_expands_no_item_where_the_task_must_not_run(self) -> None:
        cases = {
            "compose with a changed torrc": {"swarm": False, "torrc": ("manager-1",)},
            "swarm forced update": {"torrc": NODES},
            "unchanged config": {},
        }
        for name, scenario in cases.items():
            with self.subTest(name):
                self.assertEqual(expanded(**scenario), 0)
        self.assertEqual(expanded(torrc=("worker-1",)), 1)

    def test_negative_control_a_bare_node_loop_expands_in_compose(self) -> None:
        bare = [
            {**t, "loop": "{{ _tor_restart_tasks }}"}
            if MARKERS["nodes"] in _text(t)
            else t
            for t in _tasks()
        ]
        with mock.patch.object(sys.modules[__name__], "_tasks", return_value=bare):
            self.assertEqual(expanded(swarm=False, torrc=("manager-1",)), 1)

    def test_the_whole_service_rolls_once_per_play(self) -> None:
        (task,) = [t for t in _tasks() if MARKERS["forced"] in _text(t)]
        self.assertIs(task.get("run_once"), True)

    def test_a_node_restart_stops_only_its_stale_task_and_waits_for_health(
        self,
    ) -> None:
        found = [t for t in _tasks() if MARKERS["nodes"] in _text(t)]
        self.assertEqual(len(found), 1)
        (task,) = found
        self.assertIn(
            "label=com.docker.swarm.task.id={{ tor_task.stdout | quote }}",
            _text(task),
        )
        self.assertIn("--filter health=healthy", _text(task))
        self.assertEqual(task["until"], "_tor_node_restart.stdout | length > 0")
        self.assertEqual(task["delegate_to"], "{{ tor_task.tor_node }}")
        self.assertIs(task["run_once"], True)

    def test_both_probes_name_a_swarm_task_by_its_full_id(self) -> None:
        self.assertIn(
            "container service ps -q --no-trunc",
            _text(_registering("_tor_running_before")),
        )
        self.assertIn(
            '{{.Label "com.docker.swarm.task.id"}}',
            _text(_registering("_tor_running_after")),
        )


if __name__ == "__main__":
    unittest.main()
