from __future__ import annotations

import unittest

from ansible.plugins.filter.core import FilterModule
from ansible.plugins.test.core import TestModule
from jinja2.nativetypes import NativeEnvironment

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

RUN_ONE = PROJECT_ROOT / "roles" / "test-e2e-cli" / "tasks" / "run_one.yml"
RUNNER_GUARD = "_cli_runner == inventory_hostname"


def _tasks() -> list[dict]:
    """Flatten ``run_one.yml`` into its tasks.

    Returns:
        Every task, the tasks inside a ``block`` included, in file order.
    """
    pending = list(load_yaml_any(str(RUN_ONE)))
    flat: list[dict] = []
    while pending:
        task = pending.pop(0)
        flat.append(task)
        pending[:0] = task.get("block", [])
    return flat


def _task(prefix: str) -> dict:
    """Find a task of ``run_one.yml`` by the start of its name.

    Args:
        prefix: the start of the task name.

    Returns:
        The first task whose name starts with ``prefix``.
    """
    for task in _tasks():
        if task.get("name", "").startswith(prefix):
            return task
    raise LookupError(f"{RUN_ONE}: no task named {prefix}")


def _native(expression: str, **variables):
    """Render a task value the way Ansible does, keeping its native type.

    Args:
        expression: the templated value.
        **variables: the variables in scope.

    Returns:
        The rendered value.
    """
    env = NativeEnvironment()
    env.filters.update(FilterModule().filters())
    env.tests.update(TestModule().tests())
    return env.from_string(expression).render(**variables)


def _runners(claims: dict[str, str], play_hosts: list[str], stack_host: str):
    """Elect the runner every claiming host picks for its CLI node.

    Args:
        claims: the ``_cli_node_claim`` of each host that set one.
        play_hosts: ``ansible_play_hosts`` in play order.
        stack_host: the ``STACK_HOST`` of the play.

    Returns:
        The ``_cli_runner`` each claiming host computes, by host.
    """
    pick = _task("🧭 Pick")
    hostvars = {host: {"inventory_hostname": host} for host in play_hosts}
    for host, claim in claims.items():
        hostvars[host]["_cli_node_claim"] = claim
    runners = {}
    for host, claim in claims.items():
        peers = _native(
            pick["vars"]["_cli_peers"],
            ansible_play_hosts=play_hosts,
            hostvars=hostvars,
            _cli_node_claim=claim,
        )
        runners[host] = _native(
            pick["ansible.builtin.set_fact"]["_cli_runner"],
            _cli_peers=peers,
            STACK_HOST=stack_host,
        )
    return runners


class TestRunOneCliNodeOnce(unittest.TestCase):
    def test_hosts_sharing_a_cli_node_elect_the_stack_host_once(self) -> None:
        shared = dict.fromkeys(("wrk-01", "wrk-02", "mgr-01"), "app@wrk-02")
        runners = _runners(shared, ["wrk-01", "wrk-02", "mgr-01"], "mgr-01")
        self.assertEqual(set(runners.values()), {"mgr-01"})

    def test_hosts_on_distinct_cli_nodes_each_run_their_own(self) -> None:
        hosts = ["mgr-01", "wrk-01", "wrk-02"]
        runners = _runners({host: f"app@{host}" for host in hosts}, hosts, "mgr-01")
        self.assertEqual(runners, {host: host for host in hosts})

    def test_a_host_outside_the_role_is_never_elected(self) -> None:
        shared = {"wrk-01": "app@wrk-02", "wrk-02": "app@wrk-02"}
        for claims in (shared, {**shared, "mgr-01": "earlier@wrk-02"}):
            with self.subTest(claims=claims):
                runners = _runners(claims, ["mgr-01", "wrk-01", "wrk-02"], "mgr-01")
                self.assertEqual(runners["wrk-01"], "wrk-01")
                self.assertEqual(runners["wrk-02"], "wrk-01")

    def test_every_task_on_the_cli_node_runs_on_the_runner_only(self) -> None:
        delegated = [
            task
            for task in _tasks()
            if task.get("delegate_to") == "{{ CLI_HOST_NODE }}"
        ]
        self.assertGreaterEqual(len(delegated), 6)
        for task in delegated:
            with self.subTest(task=task["name"]):
                self.assertIn(RUNNER_GUARD, str(task.get("when", "")))

    def test_every_peer_records_the_failure_of_the_run_it_shares(self) -> None:
        handler = _task("❌ Handle the failed CLI test run")
        self.assertIn("hostvars[_cli_runner]._cli_run.rc", handler["when"])
        record = _task("❌ Record failure")
        self.assertNotIn(RUNNER_GUARD, str(record.get("when", "")))


if __name__ == "__main__":
    unittest.main()
