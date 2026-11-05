from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cli.administration.inventory.mesh.inventory import (
    groups_of,
    specs_of,
    topology_of,
)
from cli.administration.inventory.mesh.keys import generate_private_key, public_key_of
from cli.administration.inventory.mesh.plan import plan_mesh, primary_meshes
from cli.administration.inventory.mesh.write import (
    existing_addresses,
    existing_public_keys,
    private_key_name,
    prune_foreign_meshes,
    write_mesh,
)
from utils.cache.yaml import dump_yaml, load_yaml_any

from . import PROJECT_ROOT
from .test_plan import MESH_POOL, topology

LAYOUT = PROJECT_ROOT / "inventories/development/wireguard.yml"
EXAMPLE_LAYOUT = (
    PROJECT_ROOT / "inventories/examples/wireguard-three-meshes/wireguard.yml"
)


def layout_applications(path: Path) -> dict:
    return load_yaml_any(str(path))["applications"]


def interface_entries(host_vars: Path, host: str) -> list[dict]:
    document = load_yaml_any(str(host_vars / f"{host}.yml")) or {}
    return (
        document.get("applications", {})
        .get("svc-net-wireguard", {})
        .get("networks", {})
        .get("interfaces", [])
    )


HOSTS = ("swarm-mgr-01", "swarm-wrk-01", "swarm-wrk-02", "nfs-server", "swarm-bkp-01")

CLUSTER_INVENTORY = """\
all:
  children:
    svc-swarm-manager:
      hosts:
        swarm-mgr-01: {}
    svc-swarm-node:
      hosts:
        swarm-mgr-01: {}
        swarm-wrk-01: {}
        swarm-wrk-02: {}
    svc-storage-nfs-server:
      hosts:
        nfs-server: {}
"""

BACKUP_INVENTORY = """\
all:
  children:
    svc-bkp-remote-2-local:
      hosts:
        swarm-bkp-01: {}
"""

VAULT_PASSWORD = "mesh-test-password\n"


class MeshOnDisk(unittest.TestCase):
    LAYOUT = LAYOUT

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.host_vars = root / "host_vars"
        self.host_vars.mkdir()
        self.layout = layout_applications(self.LAYOUT)
        for host in HOSTS:
            dump_yaml(
                str(self.host_vars / f"{host}.yml"), {"applications": self.layout}
            )

        self.cluster = root / "devices.yml"
        self.cluster.write_text(self.cluster_inventory(), encoding="utf-8")
        self.backup = root / "backup.yml"
        self.backup.write_text(BACKUP_INVENTORY, encoding="utf-8")

        self.vault_file = root / ".password"
        self.vault_file.write_text(VAULT_PASSWORD, encoding="utf-8")

        self.groups = groups_of([self.cluster, self.backup])
        self.specs = specs_of(self.layout, [])
        self.topology = topology_of(self.groups, self.host_vars, self.specs)

    def cluster_inventory(self) -> str:
        return CLUSTER_INVENTORY

    def tearDown(self):
        self._tmp.cleanup()

    def _text(self, host: str) -> str:
        path = self.host_vars / f"{host}.yml"
        return path.read_text(encoding="utf-8")  # nocheck: cache-read

    def _mesh_names(self, host: str) -> list[str]:
        return sorted(
            entry["name"] for entry in interface_entries(self.host_vars, host)
        )

    def _entry(self, host: str, mesh_name: str) -> dict:
        return next(
            (
                entry
                for entry in interface_entries(self.host_vars, host)
                if entry["name"] == mesh_name
            ),
            {},
        )

    def _write_all(self, *, rotate: bool = False) -> None:
        for spec in self.specs:
            mesh = plan_mesh(
                spec,
                self.topology,
                None
                if rotate
                else existing_public_keys(self.host_vars, list(HOSTS), spec.name),
                rotate=rotate,
            )
            write_mesh(mesh, self.host_vars, self.vault_file)


class TestBothInventoriesAreRead(MeshOnDisk, unittest.TestCase):
    def test_the_backup_host_is_found_in_its_sibling_inventory(self):
        self.assertIn("swarm-bkp-01", self.groups.get("svc-bkp-remote-2-local", []))
        cluster_only = groups_of([self.cluster])
        self.assertNotIn("svc-bkp-remote-2-local", cluster_only)


class TestPrivateKeyContainment(MeshOnDisk, unittest.TestCase):
    def test_a_private_key_reaches_exactly_one_host_vars_file(self):
        for spec in self.specs:
            mesh = plan_mesh(spec, self.topology, rotate=True)
            write_mesh(mesh, self.host_vars, self.vault_file)
            with self.subTest(mesh=spec.name):
                for member in mesh.members:
                    others = [h for h in HOSTS if h != member.host]
                    for other in others:
                        self.assertNotIn(member.private_key, self._text(other))

    def test_no_plaintext_private_key_is_written_anywhere(self):
        for spec in self.specs:
            mesh = plan_mesh(spec, self.topology, rotate=True)
            write_mesh(mesh, self.host_vars, self.vault_file)
            with self.subTest(mesh=spec.name):
                for member in mesh.members:
                    self.assertNotIn(member.private_key, self._text(member.host))

    def test_the_stored_private_key_is_vault_encrypted(self):
        self._write_all()
        text = self._text("swarm-mgr-01")
        self.assertIn(private_key_name("swarm"), text)
        self.assertIn("$ANSIBLE_VAULT", text)


class TestMeshShapeOnDisk(MeshOnDisk, unittest.TestCase):
    def test_every_member_receives_the_mesh_it_belongs_to(self):
        self._write_all()
        for host in ("swarm-mgr-01", "swarm-wrk-01", "swarm-wrk-02"):
            with self.subTest(host=host):
                self.assertIn("swarm", self._mesh_names(host))
        for host in ("nfs-server", "swarm-bkp-01"):
            with self.subTest(host=host):
                self.assertIn("data", self._mesh_names(host))

    def test_a_worker_is_not_given_the_data_mesh(self):
        self._write_all()
        self.assertEqual(self._mesh_names("swarm-wrk-01"), ["swarm"])

    def test_the_hub_carries_both_meshes(self):
        self._write_all()
        self.assertEqual(self._mesh_names("swarm-mgr-01"), ["data", "swarm"])

    def test_a_spoke_routes_the_whole_pool_through_the_hub(self):
        self._write_all()
        for spec in self.specs:
            mesh = plan_mesh(spec, self.topology)
            self.assertEqual(spec.routed_range, "10.100.0.0/16")
            for spoke in mesh.spokes:
                with self.subTest(mesh=spec.name, spoke=spoke.host):
                    peers = self._entry(spoke.host, spec.name)["peers"]
                    self.assertEqual([p["host"] for p in peers], [mesh.hub.host])
                    self.assertEqual(
                        [p["allowed_ips"] for p in peers], [spec.routed_range]
                    )

    def test_the_swarm_hub_keeps_an_endpoint_for_every_spoke(self):
        self._write_all()
        for spec in self.specs:
            hub = plan_mesh(spec, self.topology).hub.host
            for peer in self._entry(hub, spec.name)["peers"]:
                with self.subTest(mesh=spec.name, peer=peer["host"]):
                    self.assertEqual(peer["host"], peer["endpoint"])

    def test_the_hub_pins_each_spoke_to_a_single_address(self):
        self._write_all()
        for spec in self.specs:
            hub = plan_mesh(spec, self.topology).hub.host
            for peer in self._entry(hub, spec.name)["peers"]:
                with self.subTest(mesh=spec.name, peer=peer["host"]):
                    self.assertFalse(peer["is_hub"])
                    self.assertEqual(peer["allowed_ips"], peer["address"] + "/32")


class TestStoredAddresses(MeshOnDisk, unittest.TestCase):
    def test_every_written_address_is_read_back(self):
        self._write_all()
        for spec in self.specs:
            mesh = plan_mesh(spec, self.topology)
            with self.subTest(mesh=spec.name):
                self.assertEqual(
                    existing_addresses(self.host_vars, list(HOSTS), spec.name),
                    {m.host: m.address for m in mesh.members},
                )

    def test_a_host_with_no_entry_is_absent_rather_than_empty(self):
        self._write_all()
        stored = existing_addresses(self.host_vars, list(HOSTS), "data")
        self.assertNotIn("swarm-wrk-01", stored)

    def test_a_mirrored_entry_is_not_read_as_the_hosts_own_address(self):
        self._write_all()
        hub_text = self._text("swarm-mgr-01")
        (self.host_vars / "swarm-wrk-01.yml").write_text(hub_text, encoding="utf-8")
        stored = existing_addresses(self.host_vars, list(HOSTS), "swarm")
        self.assertNotIn("swarm-wrk-01", stored)


class TestIdempotence(MeshOnDisk, unittest.TestCase):
    def test_a_second_run_leaves_every_file_byte_identical(self):
        self._write_all()
        before = {host: self._text(host) for host in HOSTS}
        self._write_all()
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(self._text(host), before[host])

    def test_rotation_changes_every_member_file(self):
        self._write_all()
        before = {host: self._text(host) for host in HOSTS}
        self._write_all(rotate=True)
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertNotEqual(self._text(host), before[host])

    def test_a_mirrored_host_vars_is_reminted_rather_than_adopted(self):
        self._write_all()
        hub_text = self._text("swarm-mgr-01")
        for host in ("swarm-wrk-01", "swarm-wrk-02"):
            (self.host_vars / f"{host}.yml").write_text(hub_text, encoding="utf-8")

        keyed = existing_public_keys(self.host_vars, list(HOSTS), "swarm")
        self.assertNotIn("swarm-wrk-01", keyed)
        self.assertNotIn("swarm-wrk-02", keyed)
        self.assertIn("swarm-mgr-01", keyed)

        self._write_all()
        addresses = {
            host: plan_mesh(
                self.specs[0],
                self.topology,
                existing_public_keys(self.host_vars, list(HOSTS), "swarm"),
            )
            .member(host)
            .address
            for host in ("swarm-mgr-01", "swarm-wrk-01", "swarm-wrk-02")
        }
        self.assertEqual(len(set(addresses.values())), 3)

    def test_a_mesh_a_host_does_not_own_is_pruned(self):
        self._write_all()
        hub_text = self._text("swarm-mgr-01")
        (self.host_vars / "nfs-server.yml").write_text(hub_text, encoding="utf-8")
        self.assertEqual(self._mesh_names("nfs-server"), ["data", "swarm"])

        removed = prune_foreign_meshes(self.host_vars, list(HOSTS))
        self.assertEqual(removed.get("nfs-server"), ["data", "swarm"])
        self.assertEqual(self._mesh_names("nfs-server"), [])

        self._write_all()
        self.assertEqual(self._mesh_names("nfs-server"), ["data"])

    def test_pruning_leaves_an_owned_mesh_alone(self):
        self._write_all()
        before = {host: self._text(host) for host in HOSTS}
        self.assertEqual(prune_foreign_meshes(self.host_vars, list(HOSTS)), {})
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(self._text(host), before[host])

    def test_a_member_whose_credential_vanished_is_reminted(self):
        self._write_all()
        keyed = existing_public_keys(self.host_vars, list(HOSTS), "swarm")
        self.assertIn("swarm-wrk-01", keyed)

        stripped = self._text("swarm-wrk-01").replace(
            private_key_name("swarm"), "unrelated_key"
        )
        (self.host_vars / "swarm-wrk-01.yml").write_text(stripped, encoding="utf-8")

        keyed_after = existing_public_keys(self.host_vars, list(HOSTS), "swarm")
        self.assertNotIn("swarm-wrk-01", keyed_after)


def _hub_routes(entries: list[dict]) -> dict[str, list[str]]:
    return {
        entry["name"]: [
            peer["allowed_ips"] for peer in entry["peers"] if peer["is_hub"]
        ]
        for entry in entries
        if not entry["is_hub"]
    }


class TestTheLabUnderTheThreeMeshExample(MeshOnDisk, unittest.TestCase):
    LAYOUT = EXAMPLE_LAYOUT

    def cluster_inventory(self) -> str:
        return (
            CLUSTER_INVENTORY
            + "    svc-bkp-nfs-2-local:\n      hosts:\n        nfs-server: {}\n"
        )

    def setUp(self):
        super().setUp()
        primary = primary_meshes(self.specs, self.topology)
        for spec in self.specs:
            write_mesh(
                plan_mesh(spec, self.topology),
                self.host_vars,
                self.vault_file,
                primary=primary,
            )

    def test_the_nfs_server_is_a_spoke_of_beta_and_gamma(self):
        self.assertEqual(self._mesh_names("nfs-server"), ["beta", "gamma"])

    def test_it_routes_the_pool_through_its_first_declared_mesh_only(self):
        self.assertEqual(
            _hub_routes(interface_entries(self.host_vars, "nfs-server")),
            {"beta": [MESH_POOL], "gamma": ["10.100.12.0/24"]},
        )

    def test_exactly_one_entry_per_host_is_primary(self):
        for host in HOSTS:
            with self.subTest(host=host):
                flags = [
                    entry["primary"]
                    for entry in interface_entries(self.host_vars, host)
                ]
                self.assertEqual(flags.count(True), 1)

    def test_the_hub_is_primary_on_the_first_declared_mesh(self):
        self.assertTrue(self._entry("swarm-mgr-01", "alpha")["primary"])
        self.assertFalse(self._entry("swarm-mgr-01", "beta")["primary"])


class TestNoTwoInterfacesClaimOneRoute(unittest.TestCase):
    def test_every_host_routes_each_prefix_through_one_interface(self):
        public_key = public_key_of(generate_private_key())
        for count in range(1, 9):
            for seed in range(3):
                specs, layout = topology(count, seed)
                specs = [replace(spec, routed_range=MESH_POOL) for spec in specs]
                hosts = sorted(
                    {layout.hub}
                    | {host for members in layout.spokes.values() for host in members}
                )
                primary = primary_meshes(specs, layout)
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    for spec in specs:
                        mesh = plan_mesh(spec, layout, dict.fromkeys(hosts, public_key))
                        write_mesh(mesh, root, root / ".password", primary=primary)
                    for host in hosts:
                        if not (root / f"{host}.yml").exists():
                            continue
                        entries = interface_entries(root, host)
                        routes = [
                            peer["allowed_ips"]
                            for entry in entries
                            for peer in entry["peers"]
                        ]
                        with self.subTest(meshes=count, seed=seed, host=host):
                            self.assertEqual(len(routes), len(set(routes)))
                            if _hub_routes(entries):
                                self.assertEqual(routes.count(MESH_POOL), 1)
