from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.parsing.vault import FileVaultSecret, VaultLib

from cli.administration.inventory.mesh.__main__ import main
from cli.administration.inventory.mesh.inventory import (
    declared_specs,
    groups_of,
    hub_of,
    topology_of,
)
from cli.administration.inventory.mesh.keys import public_key_of
from cli.administration.inventory.mesh.plan import plan_mesh
from cli.administration.inventory.mesh.write import private_key_name
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.manager.credential_key import CREDENTIALS_KEY, SECRETS_KEY

from .test_write import VAULT_PASSWORD, interface_entries

HUB = "galaxy"
HUB_ENDPOINT = "vpn.example.org"
SUBNET = "10.0.0.0/24"
PORT = 51871

MESHES = [{"name": "wg0", "subnet": SUBNET, "listen_port": PORT}]
DECLARATION = {"svc-net-wireguard": {"networks": {"hub": HUB, "meshes": MESHES}}}

SERVERS = """\
all:
  children:
    svc-net-wireguard:
      hosts:
        galaxy: {}
        alpha-srv: {}
        echo-srv: {}
    web-app-a:
      hosts:
        echo-srv: {}
"""

PCS = """\
all:
  children:
    svc-net-wireguard:
      hosts:
        laptop-1: {}
        laptop-2: {}
"""

ROAMING = ("alpha-srv", "laptop-1", "laptop-2")
SPOKES = ("alpha-srv", "echo-srv", "laptop-1", "laptop-2")
HOSTS = (HUB, *SPOKES)


def _joins_itself(*, roaming: bool) -> dict:
    networks: dict = {"meshes": ["wg0"]}
    if roaming:
        networks["roaming"] = True
    return {"svc-net-wireguard": {"networks": networks}}


def _decrypts_with(ciphertext: str, password_file: Path) -> str | None:
    secret = FileVaultSecret(filename=str(password_file), loader=DataLoader())
    secret.load()
    try:
        return VaultLib([("default", secret)]).decrypt(ciphertext).decode()
    except AnsibleError:
        return None


class ComposeHubOnDisk(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.host_vars = self.root / "host_vars"
        self.host_vars.mkdir()
        self.servers = self.root / "servers.yml"
        self.servers.write_text(SERVERS, encoding="utf-8")
        self.pcs = self.root / "pcs.yml"
        self.pcs.write_text(PCS, encoding="utf-8")
        dump_yaml(
            str(self.root / "group_vars" / "all.yml"), {"NETWORK_MESH_POOL": SUBNET}
        )
        self.vault_file = self.root / ".password"
        self.vault_file.write_text(VAULT_PASSWORD, encoding="utf-8")
        self.alpha_vault_file = self.root / ".alpha-password"
        self.alpha_vault_file.write_text("alpha-only-password\n", encoding="utf-8")

        self._host(HUB, DECLARATION)
        self._host("alpha-srv", _joins_itself(roaming=True))
        self._host("echo-srv", {"web-app-a": {"networks": {"meshes": ["wg0"]}}})
        self._host("laptop-1", _joins_itself(roaming=True))
        self._host("laptop-2", _joins_itself(roaming=True))

    def _host(self, host: str, *blocks: dict) -> None:
        applications: dict = {}
        for block in blocks:
            applications.update(block)
        dump_yaml(str(self.host_vars / f"{host}.yml"), {"applications": applications})

    def _inventories(self) -> list[Path]:
        return [self.servers, self.pcs]

    def _groups(self):
        return groups_of(self._inventories())

    def _topology(self):
        groups = self._groups()
        specs = declared_specs(groups, self.host_vars, self._inventories())
        return specs, topology_of(groups, self.host_vars, specs)

    def _argv(self, *extra: str) -> list[str]:
        return [
            "--inventory",
            str(self.servers),
            "--inventory",
            str(self.pcs),
            "--host-vars-dir",
            str(self.host_vars),
            "--vault-password-file",
            str(self.vault_file),
            "--endpoint",
            f"{HUB}={HUB_ENDPOINT}",
            "--host-vault-password-file",
            f"alpha-srv={self.alpha_vault_file}",
            *extra,
        ]

    def _run(self, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(self._argv(*extra))
        return code, out.getvalue(), err.getvalue()

    def _write(self) -> str:
        code, out, err = self._run()
        self.assertEqual(0, code, err)
        return out

    def _bytes(self, host: str) -> bytes:
        return (self.host_vars / f"{host}.yml").read_bytes()  # nocheck: cache-read

    def _entry(self, host: str) -> dict:
        return next(
            entry
            for entry in interface_entries(self.host_vars, host)
            if entry["name"] == "wg0"
        )

    def _peer(self, host: str, peer: str) -> dict:
        return next(p for p in self._entry(host)["peers"] if p["host"] == peer)


class TestHubSelection(ComposeHubOnDisk, unittest.TestCase):
    def test_the_named_hub_is_the_hub_without_a_swarm_manager(self):
        self.assertNotIn("svc-swarm-manager", self._groups())
        _, topology = self._topology()
        self.assertEqual(HUB, topology.hub)

    def test_the_named_hub_plans_hub_and_spoke_instead_of_a_full_mesh(self):
        specs, topology = self._topology()
        mesh = plan_mesh(specs[0], topology)
        self.assertFalse(mesh.is_full)
        self.assertEqual(HUB, mesh.hub.host)
        self.assertEqual(sorted(SPOKES), [spoke.host for spoke in mesh.spokes])

    def test_the_cli_reports_the_hub_and_its_roaming_spokes(self):
        self.assertIn(
            f"mesh 'wg0': hub {HUB} (10.0.0.1), 4 spoke(s) (3 roaming)", self._write()
        )

    def test_hosts_naming_different_hubs_are_refused(self):
        self._host(
            "echo-srv",
            {"svc-net-wireguard": {"networks": {"hub": "echo-srv"}}},
            {"web-app-a": {"networks": {"meshes": ["wg0"]}}},
        )
        with self.assertRaises(ValueError) as raised:
            hub_of(self._groups(), self.host_vars)
        self.assertIn("different hubs", str(raised.exception))

    def test_a_hub_no_inventory_holds_is_refused(self):
        self._host(
            "alpha-srv",
            {"svc-net-wireguard": {"networks": {"hub": HUB, "meshes": ["wg0"]}}},
        )
        self.servers.write_text(
            SERVERS.replace("        galaxy: {}\n", ""), encoding="utf-8"
        )
        with self.assertRaises(ValueError) as raised:
            hub_of(self._groups(), self.host_vars)
        self.assertIn(HUB, str(raised.exception))

    def test_a_named_hub_other_than_the_swarm_manager_is_refused(self):
        self.servers.write_text(
            SERVERS + "    svc-swarm-manager:\n      hosts:\n        echo-srv: {}\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError) as raised:
            hub_of(self._groups(), self.host_vars)
        self.assertIn("svc-swarm-manager", str(raised.exception))

    def test_a_hub_that_is_no_hostname_fails_the_cli(self):
        self._host(HUB, {"svc-net-wireguard": {"networks": {"hub": True}}})
        code, _, err = self._run()
        self.assertEqual(1, code)
        self.assertIn("names a host", err)

    def test_naming_the_swarm_manager_keeps_it_the_hub(self):
        self.servers.write_text(
            SERVERS + "    svc-swarm-manager:\n      hosts:\n        galaxy: {}\n",
            encoding="utf-8",
        )
        self.assertEqual(HUB, hub_of(self._groups(), self.host_vars))


class TestRoamingSpokes(ComposeHubOnDisk, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._write()

    def test_a_roaming_spoke_has_no_endpoint_in_the_hubs_peer_list(self):
        for spoke in ROAMING:
            with self.subTest(spoke=spoke):
                self.assertNotIn("endpoint", self._peer(HUB, spoke))

    def test_a_spoke_that_stays_put_keeps_its_endpoint(self):
        self.assertEqual("echo-srv", self._peer(HUB, "echo-srv")["endpoint"])

    def test_every_spoke_dials_the_hub_at_its_endpoint(self):
        for spoke in SPOKES:
            with self.subTest(spoke=spoke):
                peers = self._entry(spoke)["peers"]
                self.assertEqual([HUB], [peer["host"] for peer in peers])
                self.assertEqual(HUB_ENDPOINT, peers[0]["endpoint"])
                self.assertTrue(peers[0]["is_hub"])

    def test_the_hub_listens_and_no_spoke_does(self):
        self.assertTrue(self._entry(HUB)["is_hub"])
        for spoke in SPOKES:
            with self.subTest(spoke=spoke):
                self.assertFalse(self._entry(spoke)["is_hub"])

    def test_a_rerun_leaves_every_file_byte_identical(self):
        before = {host: self._bytes(host) for host in HOSTS}
        self._write()
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(before[host], self._bytes(host))


class TestRoamingGuards(ComposeHubOnDisk, unittest.TestCase):
    def test_roaming_without_a_hub_is_refused(self):
        self._host(HUB, {"svc-net-wireguard": {"networks": {"meshes": []}}})
        self._host(
            "alpha-srv",
            {"svc-net-wireguard": {"networks": {"meshes": MESHES, "roaming": True}}},
        )
        groups = self._groups()
        specs = declared_specs(groups, self.host_vars, self._inventories())
        with self.assertRaises(ValueError) as raised:
            topology_of(groups, self.host_vars, specs)
        self.assertIn("needs a hub", str(raised.exception))

    def test_the_hub_cannot_roam(self):
        roaming_hub = {"hub": HUB, "meshes": MESHES, "roaming": True}
        self._host(HUB, {"svc-net-wireguard": {"networks": roaming_hub}})
        with self.assertRaises(ValueError) as raised:
            self._topology()
        self.assertIn("cannot be marked roaming", str(raised.exception))

    def test_an_endpoint_for_a_roaming_spoke_aborts_before_writing(self):
        before = self._bytes(HUB)
        code, _, err = self._run("--endpoint", "laptop-1=198.51.100.7")
        self.assertEqual(1, code)
        self.assertIn("laptop-1", err)
        self.assertEqual(before, self._bytes(HUB))


class TestForwardingThroughTheHub(ComposeHubOnDisk, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._write()

    def test_every_spoke_routes_the_whole_subnet_through_the_hub(self):
        for spoke in SPOKES:
            with self.subTest(spoke=spoke):
                self.assertEqual(SUBNET, self._peer(spoke, HUB)["allowed_ips"])

    def test_the_hub_pins_each_spoke_to_its_own_address(self):
        for peer in self._entry(HUB)["peers"]:
            with self.subTest(peer=peer["host"]):
                self.assertEqual(f"{peer['address']}/32", peer["allowed_ips"])


class TestSubnetAndPort(ComposeHubOnDisk, unittest.TestCase):
    def test_every_member_keeps_the_chosen_subnet_and_port(self):
        self._write()
        for host in HOSTS:
            with self.subTest(host=host):
                entry = self._entry(host)
                self.assertEqual(SUBNET, entry["subnet"])
                self.assertEqual(PORT, entry["listen_port"])

    def test_the_hub_holds_the_first_address(self):
        self._write()
        self.assertEqual("10.0.0.1", self._entry(HUB)["address"])

    def test_the_subnet_needs_a_pool_that_holds_it(self):
        (self.root / "group_vars" / "all.yml").unlink()
        code, _, err = self._run()
        self.assertEqual(1, code)
        self.assertIn("outside the declared pool", err)

    def test_a_hand_pinned_address_is_kept(self):
        pinned = {
            "svc-net-wireguard": {
                "networks": {
                    "meshes": ["wg0"],
                    "roaming": True,
                    "interfaces": [
                        {"name": "wg0", "host": "alpha-srv", "address": "10.0.0.2"}
                    ],
                }
            }
        }
        self._host("alpha-srv", pinned)
        self._write()
        self.assertEqual("10.0.0.2", self._entry("alpha-srv")["address"])
        self.assertEqual("10.0.0.2", self._peer(HUB, "alpha-srv")["address"])


class TestPerHostVaultPassword(ComposeHubOnDisk, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._write()

    def _ciphertext(self, host: str) -> str:
        document = load_yaml_any(str(self.host_vars / f"{host}.yml"))
        app = document["applications"]["svc-net-wireguard"]
        return str(app[SECRETS_KEY][CREDENTIALS_KEY][private_key_name()])

    def test_a_host_with_its_own_password_gets_its_key_under_it(self):
        private_key = _decrypts_with(
            self._ciphertext("alpha-srv"), self.alpha_vault_file
        )
        self.assertIsNotNone(private_key)
        self.assertEqual(
            public_key_of(private_key), self._entry("alpha-srv")["public_key"]
        )

    def test_its_key_does_not_open_with_the_shared_password(self):
        self.assertIsNone(
            _decrypts_with(self._ciphertext("alpha-srv"), self.vault_file)
        )

    def test_every_other_host_uses_the_shared_password(self):
        for host in (HUB, "echo-srv", "laptop-1"):
            with self.subTest(host=host):
                self.assertIsNotNone(
                    _decrypts_with(self._ciphertext(host), self.vault_file)
                )

    def test_a_missing_password_file_aborts(self):
        code, _, err = self._run(
            "--host-vault-password-file", f"echo-srv={self.root / 'absent'}"
        )
        self.assertEqual(1, code)
        self.assertIn("not found", err)
