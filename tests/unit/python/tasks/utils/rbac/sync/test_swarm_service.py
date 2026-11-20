from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "tasks/utils/rbac/sync/register.yml"
FACT = "rbac_sync_swarm_service"
STACK_HOST = "swarm-mgr-01"
SERVICE_NAMES = {
    STACK_HOST: "postgres_postgres",
    "swarm-wrk-01": "penpot_database",
    "swarm-wrk-02": "penpot_database",
}


def _render(expression: str, variables: dict):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _conditions(task: dict) -> list[str]:
    when = task.get("when", [])
    return [when] if isinstance(when, str) else list(when)


def _names_seen_by_consumers(mode: str) -> list[dict[str, str]]:
    """Play the register tasks on every node and record the name each consumer sees.

    Args:
        mode: the ``rbac_sync_mode`` of the play.

    Returns:
        One ``{node: service name}`` map per task that reads the fact.
    """
    facts: dict[str, dict] = {host: {} for host in SERVICE_NAMES}
    seen = []
    for task in DataLoader().load_from_file(str(TASKS), trusted_as_template=True):
        assignments = task.get("ansible.builtin.set_fact") or {}
        if FACT not in assignments:
            if FACT in str(task):
                seen.append({host: facts[host][FACT] for host in facts})
            continue
        hostvars = {host: dict(values) for host, values in facts.items()}
        for host in facts:
            variables = {
                **hostvars[host],
                "rbac_sync_mode": mode,
                "rbac_sync_service_name": SERVICE_NAMES[host],
                "STACK_HOST": STACK_HOST,
                "inventory_hostname": host,
                "hostvars": hostvars,
            }
            if all(
                _render("{{ " + condition + " }}", variables)
                for condition in _conditions(task)
            ):
                facts[host][FACT] = _render(assignments[FACT], variables)
    return seen


class TestEveryNodeNamesTheStackHostsService(unittest.TestCase):
    def test_a_worker_uses_the_service_the_stack_host_names(self) -> None:
        seen = _names_seen_by_consumers("swarm")
        self.assertTrue(seen)
        for names in seen:
            with self.subTest(names=names):
                self.assertEqual(set(names.values()), {"postgres_postgres"})

    def test_compose_names_no_swarm_service(self) -> None:
        seen = _names_seen_by_consumers("compose")
        self.assertTrue(seen)
        for names in seen:
            with self.subTest(names=names):
                self.assertEqual(set(names.values()), {""})


if __name__ == "__main__":
    unittest.main()
