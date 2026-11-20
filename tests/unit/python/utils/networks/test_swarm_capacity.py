from __future__ import annotations

import ipaddress
import unittest

from utils.networks.swarm_capacity import (
    lab_swarm_nodes,
    own_containers,
    swarm_address_demand,
    usable_addresses,
)

LAB_NODES = 3

LAB_ENV = {
    "INFINITO_SWARM_BACKUP_NAME": "swarm-bkp-01",
    "INFINITO_SWARM_MGR_NAME": "swarm-mgr-01",
    "INFINITO_SWARM_NFS_NAME": "nfs-server",
    "INFINITO_SWARM_PROXMOX_NAME": "swarm-pve-01",
    "INFINITO_SWARM_TEST_LABEL": "infinito.swarm-test",
    "INFINITO_SWARM_VPN": "",
    "INFINITO_SWARM_WRK1_IP": "192.168.244.11",
    "INFINITO_SWARM_WRK1_NAME": "swarm-wrk-01",
    "INFINITO_SWARM_WRK2_IP": "192.168.244.12",
    "INFINITO_SWARM_WRK2_NAME": "swarm-wrk-02",
}

WORLDMONITOR = {
    "worldmonitor": {"name": "worldmonitor", "mem_limit": "1g"},
    "ais-relay": {"name": "relay", "replicas": 1, "mem_limit": "768m"},
    "redis-rest": {"name": "rest", "mem_limit": "512m"},
    "cache": {"name": "cache", "replicas": 1, "mem_limit": "320m"},
    "seeder": {"name": "seeder", "replicas": 1, "mem_limit": "1g"},
    "node": {"image": "node", "enabled": False, "mem_limit": "1g"},
    "sso": {"bond": 1, "enabled": "{{ 'web-app-keycloak' in group_names }}"},
    "litellm": {"bond": 1, "enabled": True, "shared": True},
}


def _demand(services: dict | None, app_hosts: int) -> int:
    return swarm_address_demand(services, app_hosts=app_hosts, swarm_nodes=LAB_NODES)[0]


class TestSwarmCapacity(unittest.TestCase):
    def test_worldmonitor_overflows_the_28_it_failed_ci_on(self) -> None:
        old = ipaddress.IPv4Network("192.168.105.64/28")
        self.assertEqual(usable_addresses(old), 13)
        self.assertEqual(_demand(WORLDMONITOR, LAB_NODES), 17)
        self.assertGreater(_demand(WORLDMONITOR, LAB_NODES), usable_addresses(old))

    def test_worldmonitor_fits_a_24(self) -> None:
        new = ipaddress.IPv4Network("192.168.88.0/24")
        self.assertLessEqual(_demand(WORLDMONITOR, LAB_NODES), usable_addresses(new))

    def test_the_lab_counts_one_node_per_worker_name(self) -> None:
        self.assertEqual(lab_swarm_nodes(LAB_ENV), LAB_NODES)

    def test_worker_ips_are_not_counted_as_nodes(self) -> None:
        names_only = {
            key: value for key, value in LAB_ENV.items() if not key.endswith("_IP")
        }
        self.assertEqual(lab_swarm_nodes(names_only), lab_swarm_nodes(LAB_ENV))
        self.assertNotEqual(
            lab_swarm_nodes(LAB_ENV),
            1 + sum(1 for key in LAB_ENV if "_WRK" in key),
        )

    def test_only_literally_enabled_containers_count(self) -> None:
        self.assertEqual(
            own_containers(WORLDMONITOR),
            ["ais-relay", "cache", "redis-rest", "seeder", "worldmonitor"],
        )

    def test_a_shared_provider_primary_still_counts(self) -> None:
        provider = {"api": {"enabled": True, "shared": True, "mem_limit": "1g"}}
        self.assertEqual(own_containers(provider), ["api"])

    def test_default_replicas_follow_the_app_hosts(self) -> None:
        single = {"app": {"mem_limit": "1g"}}
        self.assertEqual(_demand(single, app_hosts=3), 1 + 3 + 3)
        self.assertEqual(_demand(single, app_hosts=1), 1 + 1 + 1)

    def test_global_replicas_take_one_task_per_node(self) -> None:
        agent = {"agent": {"mem_limit": "64m", "replicas": "global"}}
        self.assertEqual(_demand(agent, app_hosts=1), 1 + LAB_NODES + 1)

    def test_a_role_without_services_needs_only_its_attachments(self) -> None:
        self.assertEqual(_demand({}, LAB_NODES), LAB_NODES)
        self.assertEqual(_demand(None, LAB_NODES), LAB_NODES)


if __name__ == "__main__":
    unittest.main()
