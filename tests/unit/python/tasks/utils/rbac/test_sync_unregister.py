from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "tasks/utils/rbac/sync.yml"
NFS = "svc-storage-nfs-client"
STACK_HOST = "swarm-mgr-01"
MANAGERS = (STACK_HOST, "swarm-mgr-02", "swarm-mgr-03")
WORKERS = ("swarm-wrk-01", "swarm-wrk-02")


def _unregister_task() -> dict:
    tasks = DataLoader().load_from_file(str(TASKS), trusted_as_template=True)
    (task,) = [
        task
        for task in tasks
        if (task.get("ansible.builtin.file") or {}).get("state") == "absent"
    ]
    return task


def _unregistering_hosts(
    enabled: dict[str, bool], stack_host: str, nfs_clients: set[str]
) -> set[str]:
    """
    Args:
        enabled: the ``rbac_sync_enabled`` value each host evaluates.
        stack_host: the ``STACK_HOST`` of the play.
        nfs_clients: the hosts in the svc-storage-nfs-client group.

    Returns:
        the hosts that run the unregister task.
    """
    when = _unregister_task()["when"]
    conditions = [when] if isinstance(when, str) else list(when)
    hosts = set()
    for host, flag in enabled.items():
        variables = {
            "rbac_sync_enabled": flag,
            "inventory_hostname": host,
            "STACK_HOST": stack_host,
            "group_names": [NFS] if host in nfs_clients else [],
            "IS_STACK_HOST": host in MANAGERS or host == stack_host,
        }
        templar = Templar(loader=DataLoader(), variables=variables)
        if all(
            templar.template(_trust_as_template("{{ " + condition + " }}"))
            for condition in conditions
        ):
            hosts.add(host)
    return hosts


class TestOnlyTheStackHostUnregistersAHookOnSharedState(unittest.TestCase):
    def test_a_worker_whose_flags_read_false_keeps_the_managers_hook(self) -> None:
        enabled = {STACK_HOST: True, **dict.fromkeys(WORKERS, False)}

        self.assertEqual(_unregistering_hosts(enabled, STACK_HOST, set(enabled)), set())

    def test_a_further_manager_whose_flags_read_false_keeps_the_hook(self) -> None:
        enabled = {STACK_HOST: True, **dict.fromkeys(MANAGERS[1:], False)}

        self.assertEqual(_unregistering_hosts(enabled, STACK_HOST, set(enabled)), set())

    def test_a_disabled_hook_is_unregistered_by_the_stack_host_alone(self) -> None:
        enabled = dict.fromkeys((*MANAGERS, *WORKERS), False)

        self.assertEqual(
            _unregistering_hosts(enabled, STACK_HOST, set(enabled)), {STACK_HOST}
        )

    def test_nodes_with_local_state_unregister_their_own_hook(self) -> None:
        enabled = dict.fromkeys((STACK_HOST, *WORKERS), False)

        self.assertEqual(_unregistering_hosts(enabled, STACK_HOST, set()), set(enabled))

    def test_compose_unregisters_on_its_host(self) -> None:
        self.assertEqual(
            _unregistering_hosts({"localhost": False}, "localhost", set()),
            {"localhost"},
        )


if __name__ == "__main__":
    unittest.main()
