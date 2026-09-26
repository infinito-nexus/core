"""What the mesh writer is allowed to put on disk, and what it must not.

These assertions are made against real files because the guarantees are about
files: which host_vars a secret may appear in, and whether a second run of an
unchanged mesh leaves them alone.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.mesh.inventory import groups_of, specs_of
from cli.administration.inventory.mesh.plan import plan_mesh
from cli.administration.inventory.mesh.write import (
    existing_public_keys,
    private_key_name,
    prune_foreign_meshes,
    write_mesh,
)
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

GROUP_VARS = PROJECT_ROOT / "group_vars/all/21_wireguard.yml"

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
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.host_vars = root / "host_vars"
        self.host_vars.mkdir()
        for host in HOSTS:
            (self.host_vars / f"{host}.yml").write_text("---\n", encoding="utf-8")

        self.cluster = root / "devices.yml"
        self.cluster.write_text(CLUSTER_INVENTORY, encoding="utf-8")
        self.backup = root / "backup.yml"
        self.backup.write_text(BACKUP_INVENTORY, encoding="utf-8")

        self.vault_file = root / ".password"
        self.vault_file.write_text(VAULT_PASSWORD, encoding="utf-8")

        self.groups = groups_of([self.cluster, self.backup])
        self.specs = specs_of(GROUP_VARS)

    def tearDown(self):
        self._tmp.cleanup()

    def _text(self, host: str) -> str:
        path = self.host_vars / f"{host}.yml"
        return path.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read  tempdir fixture rewritten between reads in one test

    def _mesh_names(self, host: str) -> list[str]:
        """The mesh names a host's file actually declares.

        Read structurally: the credential keys are named mesh_private_key_<n>,
        so a substring check for the mesh name matches them too and would pass
        against a file whose mesh block is empty.
        """
        document = load_yaml_any(str(self.host_vars / f"{host}.yml"))
        return sorted(
            document.get("applications", {})
            .get("svc-net-wireguard", {})
            .get("meshes", {})
        )

    def _write_all(self, *, rotate: bool = False) -> None:
        for spec in self.specs:
            mesh = plan_mesh(
                spec,
                self.groups,
                None
                if rotate
                else existing_public_keys(self.host_vars, list(HOSTS), spec.name),
                rotate=rotate,
            )
            write_mesh(mesh, self.host_vars, self.vault_file)


class TestBothInventoriesAreRead(MeshOnDisk, unittest.TestCase):
    def test_the_backup_host_is_found_in_its_sibling_inventory(self):
        """The swarm lab keeps the backup host out of the cluster inventory.

        Reading only devices.yml yields a data mesh with no backup spoke, and
        nothing downstream notices until the backup play cannot reach the hub.
        """
        self.assertIn("swarm-bkp-01", self.groups.get("svc-bkp-remote-2-local", []))
        cluster_only = groups_of([self.cluster])
        self.assertNotIn("svc-bkp-remote-2-local", cluster_only)


class TestPrivateKeyContainment(MeshOnDisk, unittest.TestCase):
    def test_a_private_key_reaches_exactly_one_host_vars_file(self):
        for spec in self.specs:
            mesh = plan_mesh(spec, self.groups, rotate=True)
            write_mesh(mesh, self.host_vars, self.vault_file)
            with self.subTest(mesh=spec.name):
                for member in mesh.members:
                    others = [h for h in HOSTS if h != member.host]
                    for other in others:
                        self.assertNotIn(member.private_key, self._text(other))

    def test_no_plaintext_private_key_is_written_anywhere(self):
        for spec in self.specs:
            mesh = plan_mesh(spec, self.groups, rotate=True)
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
        """Workers reach NFS through the hub, not as data-plane members.

        A worker that carried the data mesh would peer with the NFS server
        directly and bypass the routing the topology depends on.
        """
        self._write_all()
        self.assertEqual(self._mesh_names("swarm-wrk-01"), ["swarm"])

    def test_the_hub_carries_both_meshes(self):
        self._write_all()
        self.assertEqual(self._mesh_names("swarm-mgr-01"), ["data", "swarm"])

    def test_a_spoke_routes_the_whole_pool_through_the_hub(self):
        """A worker must reach the data plane it is not a member of.

        Pinning a spoke's AllowedIPs to its own mesh subnet leaves the worker
        with no route to the NFS server, and the mount fails while every tunnel
        still reports a healthy handshake -- so the symptom points at storage
        rather than at routing.
        """
        self._write_all()
        for spec in self.specs:
            mesh = plan_mesh(spec, self.groups)
            for spoke in mesh.spokes:
                with self.subTest(mesh=spec.name, spoke=spoke.host):
                    peers = mesh.peers_of(spoke.host)
                    self.assertEqual([p.host for p in peers], [mesh.hub.host])
                    self.assertEqual(spec.routed_range, "10.100.0.0/16")

    def test_the_hub_pins_each_spoke_to_a_single_address(self):
        """The inverse of the spoke rule.

        A hub that routed the pool to one spoke would blackhole every other
        member behind it.
        """
        self._write_all()
        for spec in self.specs:
            mesh = plan_mesh(spec, self.groups)
            for peer in mesh.peers_of(mesh.hub.host):
                with self.subTest(mesh=spec.name, peer=peer.host):
                    self.assertFalse(peer.is_hub)


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
        """The swarm reset copies one node's host_vars over every other.

        That is right for credentials identical on every host and wrong here:
        each node would adopt the hub's key and address, every interface would
        claim 10.100.0.1, and no tunnel would handshake. An entry naming a
        different host has to count as unkeyed.
        """
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
                self.groups,
                existing_public_keys(self.host_vars, list(HOSTS), "swarm"),
            )
            .member(host)
            .address
            for host in ("swarm-mgr-01", "swarm-wrk-01", "swarm-wrk-02")
        }
        self.assertEqual(len(set(addresses.values())), 3)

    def test_a_mesh_a_host_does_not_own_is_pruned(self):
        """Rewriting a member's own entry never removes a foreign one.

        After the mirror the NFS server keeps the hub's swarm entry, brings up
        an interface claiming 10.100.0.1, and swallows the return path for
        every worker -- while its own data mesh looks perfectly healthy.
        """
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
        """A public key with no private key behind it is worse than no key.

        The peers accept it, the owner cannot use it, and the tunnel fails only
        when traffic is attempted.
        """
        self._write_all()
        keyed = existing_public_keys(self.host_vars, list(HOSTS), "swarm")
        self.assertIn("swarm-wrk-01", keyed)

        stripped = self._text("swarm-wrk-01").replace(
            private_key_name("swarm"), "unrelated_key"
        )
        (self.host_vars / "swarm-wrk-01.yml").write_text(stripped, encoding="utf-8")

        keyed_after = existing_public_keys(self.host_vars, list(HOSTS), "swarm")
        self.assertNotIn("swarm-wrk-01", keyed_after)
