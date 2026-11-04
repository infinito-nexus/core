from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.mesh.inventory import (
    groups_of,
    hub_of,
    pool_of,
    specs_of,
    topology_of,
)
from utils.cache.yaml import dump_yaml, load_yaml_any

from . import PROJECT_ROOT

DECLARED = {
    "svc-net-wireguard": {
        "networks": {
            "meshes": [
                {"name": "alpha", "subnet": "10.100.10.0/24", "listen_port": 51830},
                {"name": "beta", "subnet": "10.100.11.0/24", "listen_port": 51831},
            ]
        }
    }
}

GROUPS = {
    "svc-swarm-manager": ["mgr"],
    "svc-swarm-node": ["mgr", "wrk-1", "wrk-2"],
    "svc-storage-nfs-server": ["nfs"],
    "svc-bkp-nfs-2-local": ["nfs"],
}


def _joins(role: str, *meshes: str) -> dict:
    return {role: {"networks": {"meshes": list(meshes)}}}


class InventoryOnDisk(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.host_vars = self.root / "host_vars"
        self.host_vars.mkdir()

    def _host(self, host: str, *blocks: dict) -> None:
        applications: dict = {}
        for block in blocks:
            applications.update(block)
        dump_yaml(str(self.host_vars / f"{host}.yml"), {"applications": applications})

    def _topology(self, groups=None):
        specs = specs_of(DECLARED, [])
        return topology_of(groups or GROUPS, self.host_vars, specs)


class TestDeclarations(unittest.TestCase):
    def test_the_meshes_keep_their_declaration_order(self):
        self.assertEqual(["alpha", "beta"], [s.name for s in specs_of(DECLARED, [])])

    def test_a_silent_declaration_routes_the_platform_pool(self):
        self.assertEqual("10.100.0.0/16", specs_of(DECLARED, [])[0].routed_range)

    def test_an_inventory_without_declarations_is_refused(self):
        with self.assertRaises(ValueError) as raised:
            specs_of({}, [])
        self.assertIn("networks.meshes", str(raised.exception))

    def test_a_mesh_declared_twice_is_refused(self):
        twice = {
            "svc-net-wireguard": {
                "networks": {
                    "meshes": [
                        {"name": "a", "subnet": "10.100.1.0/24", "listen_port": 1},
                        {"name": "a", "subnet": "10.100.2.0/24", "listen_port": 2},
                    ]
                }
            }
        }
        with self.assertRaises(ValueError):
            specs_of(twice, [])


class TestPool(InventoryOnDisk, unittest.TestCase):
    def test_the_platform_pool_applies_by_default(self):
        self.assertEqual("10.100.0.0/16", pool_of([]))

    def test_a_deployment_narrows_it_in_its_own_group_vars(self):
        inventory = self.root / "devices.yml"
        inventory.write_text("all: {}\n", encoding="utf-8")
        (self.root / "group_vars").mkdir()
        dump_yaml(
            str(self.root / "group_vars" / "all.yml"),
            {"NETWORK_MESH_POOL": "10.100.0.0/17"},
        )
        self.assertEqual("10.100.0.0/17", pool_of([inventory]))
        self.assertEqual(
            "10.100.0.0/17", specs_of(DECLARED, [inventory])[0].routed_range
        )


class TestTopology(InventoryOnDisk, unittest.TestCase):
    def test_a_host_joins_what_its_roles_list(self):
        self._host("wrk-1", _joins("svc-swarm-node", "alpha"))
        self._host("nfs", _joins("svc-storage-nfs-server", "beta"))
        topology = self._topology()
        self.assertEqual(("wrk-1",), topology.spokes["alpha"])
        self.assertEqual(("nfs",), topology.spokes["beta"])

    def test_two_hosts_of_one_role_may_sit_in_different_meshes(self):
        self._host("wrk-1", _joins("svc-swarm-node", "alpha"))
        self._host("wrk-2", _joins("svc-swarm-node", "beta"))
        topology = self._topology()
        self.assertEqual(("wrk-1",), topology.spokes["alpha"])
        self.assertEqual(("wrk-2",), topology.spokes["beta"])

    def test_two_roles_naming_one_mesh_admit_the_host_once(self):
        self._host(
            "nfs",
            _joins("svc-storage-nfs-server", "beta"),
            _joins("svc-bkp-nfs-2-local", "beta"),
        )
        self.assertEqual(("nfs",), self._topology().spokes["beta"])

    def test_a_role_the_host_does_not_carry_admits_nothing(self):
        self._host("wrk-1", _joins("svc-storage-nfs-server", "beta"))
        self.assertEqual((), self._topology().spokes["beta"])

    def test_the_hub_is_in_every_mesh_and_never_a_spoke(self):
        self._host("mgr", DECLARED, _joins("svc-swarm-node", "alpha"))
        topology = self._topology()
        self.assertEqual("mgr", topology.hub)
        self.assertNotIn("mgr", topology.spokes["alpha"])

    def test_a_mesh_nobody_declared_is_refused(self):
        self._host("wrk-1", _joins("svc-swarm-node", "omega"))
        with self.assertRaises(ValueError) as raised:
            self._topology()
        self.assertIn("omega", str(raised.exception))
        self.assertIn("svc-swarm-node", str(raised.exception))

    def test_the_declaring_role_itself_joins_nothing(self):
        self._host("wrk-1", DECLARED)
        groups = {**GROUPS, "svc-net-wireguard": ["wrk-1"]}
        self.assertEqual((), self._topology(groups).spokes["alpha"])

    def test_a_hub_role_with_two_hosts_is_refused(self):
        with self.assertRaises(ValueError):
            hub_of({**GROUPS, "svc-swarm-manager": ["a", "b"]}, self.host_vars)

    def test_an_inventory_without_a_hub_host_has_no_hub(self):
        self.assertIsNone(hub_of({**GROUPS, "svc-swarm-manager": []}, self.host_vars))

    def test_the_swarm_manager_stays_the_hub_without_a_named_one(self):
        self._host("mgr", DECLARED)
        self.assertEqual("mgr", hub_of(GROUPS, self.host_vars))


class TestTheShippedExample(InventoryOnDisk, unittest.TestCase):
    EXAMPLE = PROJECT_ROOT / "inventories" / "examples" / "wireguard-three-meshes"

    def setUp(self):
        super().setUp()
        layout = load_yaml_any(str(self.EXAMPLE / "wireguard.yml"))["applications"]
        self.groups = groups_of([self.EXAMPLE / "inventory.yml"])
        for host in {h for members in self.groups.values() for h in members}:
            self._host(host, layout)
        self.specs = specs_of(layout, [])
        self.topology = topology_of(self.groups, self.host_vars, self.specs)

    def test_it_declares_more_than_two_meshes(self):
        self.assertEqual(["alpha", "beta", "gamma"], [s.name for s in self.specs])

    def test_every_mesh_routes_the_whole_pool_so_the_planes_can_reach_each_other(self):
        for spec in self.specs:
            with self.subTest(mesh=spec.name):
                self.assertEqual("10.100.0.0/16", spec.routed_range)

    def test_every_mesh_gets_the_members_its_table_promises(self):
        self.assertEqual("mesh-hub-01", self.topology.hub)
        self.assertEqual(
            {
                "alpha": ("mesh-wrk-01", "mesh-wrk-02"),
                "beta": ("mesh-nfs-01",),
                "gamma": ("mesh-bkp-01",),
            },
            self.topology.spokes,
        )
