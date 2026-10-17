from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.mesh.inventory import (
    groups_of,
    specs_of,
    topology_of,
)
from cli.administration.inventory.mesh.plan import members_of, plan_mesh
from cli.administration.inventory.mesh.transport import (
    MESH_CONTROL_PERSIST,
    mesh_address,
    mesh_ssh_args,
    repo_ssh_args,
    switch_to_mesh,
)
from cli.administration.inventory.mesh.write import write_mesh
from utils.cache.yaml import dump_yaml

from .test_write import LAYOUT, layout_applications

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
        layout = layout_applications(LAYOUT)
        for host in HOSTS:
            dump_yaml(str(self.host_vars / f"{host}.yml"), {"applications": layout})
        self.cluster = root / "devices.yml"
        self.cluster.write_text(CLUSTER_INVENTORY, encoding="utf-8")
        self.vault_file = root / ".password"
        self.vault_file.write_text("mesh-test-password\n", encoding="utf-8")
        self.groups = groups_of([self.cluster])
        self.specs = specs_of(layout, [])
        self.topology = topology_of(self.groups, self.host_vars, self.specs)
        self.swarm = next(spec for spec in self.specs if spec.name == "swarm")

    def tearDown(self):
        self._tmp.cleanup()

    def _write_swarm(self):
        mesh = plan_mesh(self.swarm, self.topology, rotate=True, controller=CONTROLLER)
        write_mesh(mesh, self.host_vars, self.vault_file)
        return mesh

    def _text(self, host: str) -> str:
        return (self.host_vars / f"{host}.yml").read_text(  # nocheck: cache-read
            encoding="utf-8"
        )


class TestTheControllerJoinsTheMesh(MeshOnDisk, unittest.TestCase):
    def test_it_is_admitted_as_an_ordinary_spoke(self):
        _, spokes = members_of(self.swarm, self.topology, CONTROLLER)
        self.assertIn(CONTROLLER, spokes)

    def test_it_stays_out_when_it_is_not_named(self):
        _, spokes = members_of(self.swarm, self.topology)
        self.assertNotIn(CONTROLLER, spokes)

    def test_it_is_never_made_the_hub(self):
        hub, _ = members_of(self.swarm, self.topology, CONTROLLER)
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
        self._write_swarm()
        switched = self._switch()
        self.assertNotIn("nfs-server", switched)

    def test_the_connection_moves_to_ssh(self):
        self._write_swarm()
        self._switch()
        text = self._text("swarm-wrk-01")
        self.assertIn("ansible_connection: ssh", text)
        self.assertIn("ansible_user: administrator", text)

    def test_a_switched_host_carries_the_meshs_own_ssh_args(self):
        self._write_swarm()
        self._switch()
        text = self._text("swarm-wrk-01")
        self.assertIn("ansible_ssh_args:", text)
        self.assertIn(f"ControlPersist={MESH_CONTROL_PERSIST}", text)

    def test_a_switched_host_asks_for_no_tty(self):
        self._write_swarm()
        self._switch()
        self.assertIn("ansible_ssh_use_tty: false", self._text("swarm-wrk-01"))

    def test_switching_before_the_mesh_exists_changes_nothing(self):
        self.assertEqual(self._switch(), {})

    def test_the_address_is_only_read_from_the_host_that_owns_it(self):
        self._write_swarm()
        (self.host_vars / "swarm-wrk-01.yml").write_text(
            self._text("swarm-mgr-01"), encoding="utf-8"
        )
        self.assertIsNone(mesh_address(self.host_vars, "swarm-wrk-01", "swarm"))


class TestTheMeshRetunesItsOwnTransport(unittest.TestCase):
    BASE = (
        "-o ControlMaster=auto -o ControlPersist=20s "
        "-o ControlPath=~/.ssh/ansible-%h-%p-%r -o ServerAliveInterval=15"
    )

    def test_the_window_is_the_meshs_own(self):
        args = mesh_ssh_args(self.BASE)
        self.assertIn(f"-o ControlPersist={MESH_CONTROL_PERSIST}", args)
        self.assertNotIn("ControlPersist=20s", args)

    def test_the_socket_is_left_to_ansible(self):
        self.assertNotIn("ControlPath", mesh_ssh_args(self.BASE))

    def test_every_other_option_survives(self):
        args = mesh_ssh_args(self.BASE)
        self.assertIn("-o ControlMaster=auto", args)
        self.assertIn("-o ServerAliveInterval=15", args)

    def test_a_bare_flag_is_not_dropped(self):
        self.assertIn("-C", mesh_ssh_args("-C -o ControlPersist=20s"))

    def test_the_repository_value_is_the_one_retuned(self):
        base = repo_ssh_args()
        self.assertIn("ControlMaster", base)
        for option in base.split(" -o "):
            name = option.split("=")[0].lstrip("-o ").strip()
            if name and not name.startswith(("ControlPersist", "ControlPath")):
                with self.subTest(option=name):
                    self.assertIn(name, mesh_ssh_args(base))
