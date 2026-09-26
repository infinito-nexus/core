"""Moving the Ansible transport onto the mesh the deploy just built.

The first pass reaches the hosts however it can, because it is what creates
the tunnel. Every pass after it connects over the mesh, which is the only way
the mesh is load-bearing rather than merely present: a broken tunnel then
fails the deploy at the connection instead of letting a role fall back to the
underlay it was supposed to stop using.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.mesh.inventory import groups_of, specs_of
from cli.administration.inventory.mesh.plan import members_of, plan_mesh
from cli.administration.inventory.mesh.transport import mesh_address, switch_to_mesh
from cli.administration.inventory.mesh.write import write_mesh

from . import PROJECT_ROOT

GROUP_VARS = PROJECT_ROOT / "group_vars/all/21_wireguard.yml"
CONTROLLER = "localhost"
HOSTS = ("swarm-mgr-01", "swarm-wrk-01", "nfs-server", CONTROLLER)

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
    svc-storage-nfs-server:
      hosts:
        nfs-server: {}
"""


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
        self.vault_file = root / ".password"
        self.vault_file.write_text("mesh-test-password\n", encoding="utf-8")
        self.groups = groups_of([self.cluster])
        self.specs = specs_of(GROUP_VARS)
        self.swarm = next(spec for spec in self.specs if spec.name == "swarm")

    def tearDown(self):
        self._tmp.cleanup()

    def _write_swarm(self):
        mesh = plan_mesh(self.swarm, self.groups, rotate=True, controller=CONTROLLER)
        write_mesh(mesh, self.host_vars, self.vault_file)
        return mesh


class TestTheControllerJoinsTheMesh(MeshOnDisk, unittest.TestCase):
    def test_it_is_admitted_as_an_ordinary_spoke(self):
        _, spokes = members_of(self.swarm, self.groups, CONTROLLER)
        self.assertIn(CONTROLLER, spokes)

    def test_it_stays_out_when_it_is_not_named(self):
        """It belongs to no role group, so nothing else can pull it in."""
        _, spokes = members_of(self.swarm, self.groups)
        self.assertNotIn(CONTROLLER, spokes)

    def test_it_is_never_made_the_hub(self):
        hub, _ = members_of(self.swarm, self.groups, CONTROLLER)
        self.assertNotEqual(hub, CONTROLLER)

    def test_it_gets_an_address_of_its_own(self):
        mesh = self._write_swarm()
        addresses = {member.host: member.address for member in mesh.members}
        self.assertIn(CONTROLLER, addresses)
        self.assertEqual(len(set(addresses.values())), len(addresses))


class TestSwitchingTheTransport(MeshOnDisk, unittest.TestCase):
    def _switch(self):
        return switch_to_mesh(
            self.host_vars,
            list(HOSTS),
            "swarm",
            user="administrator",
            private_key_file="/tmp/key",
        )

    def test_every_member_is_pointed_at_its_mesh_address(self):
        mesh = self._write_swarm()
        switched = self._switch()
        for member in mesh.members:
            with self.subTest(host=member.host):
                self.assertEqual(switched[member.host], member.address)

    def test_a_non_member_is_left_reachable(self):
        """Rewriting a host that holds no mesh address would strand it."""
        self._write_swarm()
        switched = self._switch()
        self.assertNotIn("nfs-server", switched)

    def test_the_connection_moves_to_ssh(self):
        self._write_swarm()
        self._switch()
        text = (
            self.host_vars / "swarm-wrk-01.yml"
        ).read_text(  # nocheck: cache-read  tempdir fixture rewritten between reads in one test
            encoding="utf-8"
        )
        self.assertIn("ansible_connection: ssh", text)
        self.assertIn("ansible_user: administrator", text)

    def test_switching_before_the_mesh_exists_changes_nothing(self):
        """The first pass is what creates the mesh; there is nothing to move to."""
        self.assertEqual(self._switch(), {})

    def test_the_address_is_only_read_from_the_host_that_owns_it(self):
        """The swarm reset mirrors one node's host_vars over every other."""
        self._write_swarm()
        mirrored = (
            self.host_vars / "swarm-mgr-01.yml"
        ).read_text(  # nocheck: cache-read  tempdir fixture rewritten between reads in one test
            encoding="utf-8"
        )
        (self.host_vars / "swarm-wrk-01.yml").write_text(mirrored, encoding="utf-8")
        self.assertIsNone(mesh_address(self.host_vars, "swarm-wrk-01", "swarm"))
