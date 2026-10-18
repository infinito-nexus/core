from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from cli.administration.inventory.mesh.__main__ import main
from cli.administration.inventory.mesh.inventory import (
    declared_specs,
    groups_of,
    topology_of,
)
from cli.administration.inventory.mesh.plan import plan_mesh, primary_meshes
from utils.cache.yaml import dump_yaml

from .test_write import VAULT_PASSWORD, interface_entries

DECLARED = {
    "svc-net-wireguard": {
        "networks": {
            "meshes": [
                {"name": "alpha", "subnet": "10.100.20.0/24", "listen_port": 51840},
                {"name": "beta", "subnet": "10.100.21.0/24", "listen_port": 51841},
            ]
        }
    }
}

INVENTORY = """\
all:
  children:
    svc-net-wireguard:
      hosts:
        host-1: {}
        host-2: {}
        host-3: {}
        host-4: {}
    web-app-a:
      hosts:
        host-1: {}
        host-2: {}
        host-3: {}
        host-4: {}
"""

MEMBERSHIP = {
    "host-1": ["alpha"],
    "host-2": ["alpha", "beta"],
    "host-3": ["beta"],
    "host-4": ["alpha"],
}


class FullMeshOnDisk(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.host_vars = self.root / "host_vars"
        self.host_vars.mkdir()
        self.inventory = self.root / "devices.yml"
        self.inventory.write_text(INVENTORY, encoding="utf-8")
        self.vault_file = self.root / ".password"
        self.vault_file.write_text(VAULT_PASSWORD, encoding="utf-8")
        for host, meshes in MEMBERSHIP.items():
            self._host(host, meshes)

    def _host(self, host: str, meshes: list[str], declared: dict | None = None):
        applications = {
            **(DECLARED if declared is None else declared),
            "web-app-a": {"networks": {"meshes": meshes}},
        }
        dump_yaml(str(self.host_vars / f"{host}.yml"), {"applications": applications})

    def _groups(self):
        return groups_of([self.inventory])

    def _write(self) -> str:
        argv = [
            "--inventory",
            str(self.inventory),
            "--host-vars-dir",
            str(self.host_vars),
            "--vault-password-file",
            str(self.vault_file),
        ]
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(0, main(argv))
        return out.getvalue()

    def _entry(self, host: str, mesh: str) -> dict:
        return next(
            entry
            for entry in interface_entries(self.host_vars, host)
            if entry["name"] == mesh
        )


class TestDeclarations(FullMeshOnDisk, unittest.TestCase):
    def test_every_host_may_declare_the_meshes(self):
        specs = declared_specs(self._groups(), self.host_vars, [self.inventory])
        self.assertEqual(["alpha", "beta"], [spec.name for spec in specs])

    def test_a_host_declaring_nothing_reads_the_others(self):
        self._host("host-1", ["alpha"], declared={})
        specs = declared_specs(self._groups(), self.host_vars, [self.inventory])
        self.assertEqual(["alpha", "beta"], [spec.name for spec in specs])

    def test_hosts_declaring_different_meshes_are_refused(self):
        other = {
            "svc-net-wireguard": {
                "networks": {
                    "meshes": [
                        {
                            "name": "alpha",
                            "subnet": "10.100.30.0/24",
                            "listen_port": 51840,
                        }
                    ]
                }
            }
        }
        self._host("host-3", ["alpha"], declared=other)
        with self.assertRaises(ValueError) as raised:
            declared_specs(self._groups(), self.host_vars, [self.inventory])
        self.assertIn("host-3", str(raised.exception))

    def test_no_host_declaring_any_mesh_is_refused(self):
        for host, meshes in MEMBERSHIP.items():
            self._host(host, meshes, declared={})
        with self.assertRaises(ValueError) as raised:
            declared_specs(self._groups(), self.host_vars, [self.inventory])
        self.assertIn("networks.meshes", str(raised.exception))


class TestPlanning(FullMeshOnDisk, unittest.TestCase):
    def setUp(self):
        super().setUp()
        groups = self._groups()
        self.specs = declared_specs(groups, self.host_vars, [self.inventory])
        self.topology = topology_of(groups, self.host_vars, self.specs)
        self.alpha = plan_mesh(self.specs[0], self.topology)

    def test_there_is_no_hub(self):
        self.assertIsNone(self.topology.hub)
        self.assertTrue(self.alpha.is_full)
        self.assertFalse(any(member.is_hub for member in self.alpha.members))

    def test_every_member_peers_with_every_other(self):
        hosts = {member.host for member in self.alpha.members}
        self.assertEqual({"host-1", "host-2", "host-4"}, hosts)
        for host in hosts:
            with self.subTest(host=host):
                peers = {peer.host for peer in self.alpha.peers_of(host)}
                self.assertEqual(hosts - {host}, peers)

    def test_no_two_members_share_an_address(self):
        addresses = [member.address for member in self.alpha.members]
        self.assertEqual(len(addresses), len(set(addresses)))

    def test_a_host_of_two_meshes_is_primary_on_the_first(self):
        primary = primary_meshes(self.specs, self.topology)
        self.assertEqual("alpha", primary["host-2"])
        self.assertEqual("beta", primary["host-3"])


class TestWritten(FullMeshOnDisk, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.out = self._write()

    def test_the_cli_reports_full_meshes(self):
        self.assertIn("mesh 'alpha': full mesh of 3 member(s)", self.out)
        self.assertIn("mesh 'beta': full mesh of 2 member(s)", self.out)

    def test_every_peer_is_pinned_to_its_own_address(self):
        for host, meshes in MEMBERSHIP.items():
            for mesh in meshes:
                entry = self._entry(host, mesh)
                for peer in entry["peers"]:
                    with self.subTest(host=host, mesh=mesh, peer=peer["host"]):
                        self.assertEqual(f"{peer['address']}/32", peer["allowed_ips"])
                        self.assertFalse(peer["is_hub"])

    def test_no_member_is_a_hub(self):
        for host, meshes in MEMBERSHIP.items():
            for mesh in meshes:
                with self.subTest(host=host, mesh=mesh):
                    self.assertFalse(self._entry(host, mesh)["is_hub"])

    def test_a_host_of_one_mesh_holds_no_peer_of_the_other(self):
        beta_only = {"host-3"}
        for host in ("host-1", "host-4"):
            with self.subTest(host=host):
                self.assertEqual(
                    ["alpha"],
                    [e["name"] for e in interface_entries(self.host_vars, host)],
                )
                peers = {p["host"] for p in self._entry(host, "alpha")["peers"]}
                self.assertFalse(peers & beta_only)

    def test_the_host_in_both_meshes_peers_with_both(self):
        alpha = {p["host"] for p in self._entry("host-2", "alpha")["peers"]}
        beta = {p["host"] for p in self._entry("host-2", "beta")["peers"]}
        self.assertEqual({"host-1", "host-4"}, alpha)
        self.assertEqual({"host-3"}, beta)

    def test_a_second_run_leaves_every_file_byte_identical(self):
        before = {
            path.name: path.read_bytes()  # nocheck: cache-read
            for path in self.host_vars.glob("*.yml")
        }
        self._write()
        after = {
            path.name: path.read_bytes()  # nocheck: cache-read
            for path in self.host_vars.glob("*.yml")
        }
        self.assertEqual(before, after)
