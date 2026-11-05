"""The guard that stops a swarm deploy with public LDAPS before OpenLDAP runs.

Public LDAPS relays through the stream module of openresty. In swarm that relay
has no live proof that it reaches slapd, so a deploy that switches
``services.openldap.network.public`` on in swarm stops right after the run-once
flag, before any other task of the role. Every compose deploy and every swarm
deploy without public LDAPS passes.
"""

from __future__ import annotations

import copy
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

CORE = PROJECT_ROOT / "roles/svc-db-openldap/tasks/00_core.yml"
REQUIREMENT_TITLE = "OpenLDAP LDAPS through openresty in swarm"
PUBLIC_SWITCH = "services.openldap.network.public"


def _tasks() -> list[dict]:
    return load_yaml_any(str(CORE), default_if_missing=[])


def _is_guard(task: dict) -> bool:
    assertion = task.get("ansible.builtin.assert") or {}
    return REQUIREMENT_TITLE in str(assertion.get("fail_msg", ""))


def _guard(tasks: list[dict]) -> dict:
    return next(task for task in tasks if _is_guard(task))


def _holds(condition: str, facts: dict) -> bool:
    templar = Templar(loader=DataLoader(), variables=facts)
    return templar.template(_trust_as_template("{{ (" + condition + ") | bool }}"))


def _passes(task: dict, *, swarm: object, public: object) -> bool:
    """Evaluate the guard the way Ansible's assert does.

    Args:
      task: the assert task.
      swarm: the value IS_SWARM_MODE renders to.
      public: the value OPENLDAP_NETWORK_SWITCH_PUBLIC renders to.

    Returns:
      whether every condition of the assert holds.
    """
    facts = {"IS_SWARM_MODE": swarm, "OPENLDAP_NETWORK_SWITCH_PUBLIC": public}
    conditions = task["ansible.builtin.assert"]["that"]
    return all(_holds(condition, facts) for condition in conditions)


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


class TestTheGuardStopsOnlyPublicLdapsInSwarm(unittest.TestCase):
    def test_a_swarm_deploy_with_public_ldaps_stops(self):
        self.assertFalse(_passes(_guard(_tasks()), swarm=True, public=True))

    def test_a_swarm_deploy_reads_string_flags_the_same_way(self):
        self.assertFalse(_passes(_guard(_tasks()), swarm="True", public="true"))

    def test_a_swarm_deploy_without_public_ldaps_passes(self):
        self.assertTrue(_passes(_guard(_tasks()), swarm=True, public=False))

    def test_a_compose_deploy_with_public_ldaps_passes(self):
        self.assertTrue(_passes(_guard(_tasks()), swarm=False, public=True))

    def test_a_compose_deploy_without_public_ldaps_passes(self):
        self.assertTrue(_passes(_guard(_tasks()), swarm=False, public=False))


class TestTheGuardFailsFastAndSaysWhy(unittest.TestCase):
    def test_the_guard_directly_follows_the_run_once_flag(self):
        tasks = _tasks()
        self.assertEqual(tasks[0], {"include_tasks": "utils/once/flag.yml"})
        self.assertEqual(_index(tasks, _is_guard), 1)

    def test_the_guard_runs_before_any_container_is_touched(self):
        tasks = _tasks()
        docker = _index(
            tasks, lambda task: task.get("include_tasks") == "01_docker.yml"
        )
        self.assertLess(_index(tasks, _is_guard), docker)

    def test_the_guard_runs_before_the_stream_config_is_rendered(self):
        tasks = _tasks()
        stream = _index(
            tasks,
            lambda task: (
                task.get("stack_host_template", {}).get("src") == "nginx.stream.conf.j2"
            ),
        )
        self.assertLess(_index(tasks, _is_guard), stream)

    def test_the_message_names_the_switch_and_the_requirement(self):
        message = _guard(_tasks())["ansible.builtin.assert"]["fail_msg"]
        self.assertIn(PUBLIC_SWITCH, message)
        self.assertIn(REQUIREMENT_TITLE, message)
        self.assertIn("docs/requirements/", message)


class TestNegativeControl(unittest.TestCase):
    def test_a_guard_without_its_condition_lets_public_ldaps_through(self):
        guard = copy.deepcopy(_guard(_tasks()))
        guard["ansible.builtin.assert"]["that"] = ["true"]
        self.assertTrue(_passes(guard, swarm=True, public=True))

    def test_a_guard_that_ignores_the_mode_stops_compose_too(self):
        guard = copy.deepcopy(_guard(_tasks()))
        guard["ansible.builtin.assert"]["that"] = [
            "not (OPENLDAP_NETWORK_SWITCH_PUBLIC | bool)"
        ]
        self.assertFalse(_passes(guard, swarm=False, public=True))


if __name__ == "__main__":
    unittest.main()
