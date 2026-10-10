"""The mesh CLI as the swarm routine invokes it."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.mesh.__main__ import main
from utils.cache.yaml import load_yaml_any

from .test_write import (
    BACKUP_INVENTORY,
    CLUSTER_INVENTORY,
    GROUP_VARS,
    HOSTS,
    VAULT_PASSWORD,
)

CONTROLLER = "deploy-controller"
SWARM_HOSTS = ("swarm-mgr-01", "swarm-wrk-01", "swarm-wrk-02")


class TestMeshCli(unittest.TestCase):
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

    def tearDown(self):
        self._tmp.cleanup()

    def _text(self, host: str) -> str:
        path = self.host_vars / f"{host}.yml"
        return path.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read  tempdir fixture rewritten between reads in one test

    def _argv(self, *extra: str) -> list[str]:
        return [
            "--inventory",
            str(self.cluster),
            "--inventory",
            str(self.backup),
            "--host-vars-dir",
            str(self.host_vars),
            "--vault-password-file",
            str(self.vault_file),
            "--group-vars-file",
            str(GROUP_VARS),
            *extra,
        ]

    def test_one_invocation_writes_every_member(self):
        self.assertEqual(main(self._argv()), 0)
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertIn("$ANSIBLE_VAULT", self._text(host))

    def test_a_missing_host_vars_dir_fails_rather_than_writing_nothing(self):
        argv = self._argv()
        argv[argv.index("--host-vars-dir") + 1] = str(self.host_vars / "absent")
        self.assertEqual(main(argv), 1)

    def test_an_unknown_mesh_name_fails(self):
        self.assertEqual(main(self._argv("--mesh", "no-such-mesh")), 1)

    def test_restricting_to_one_mesh_leaves_the_other_unwritten(self):
        self.assertEqual(main(self._argv("--mesh", "swarm")), 0)
        self.assertNotIn("data:", self._text("nfs-server"))

    def test_the_controller_is_pruned_although_no_group_holds_it(self):
        argv = self._argv("--controller", CONTROLLER, "--controller-mesh", "swarm")
        self.assertEqual(main(argv), 0)
        (self.host_vars / f"{CONTROLLER}.yml").write_text(
            self._text("swarm-mgr-01"), encoding="utf-8"
        )

        self.assertEqual(main(argv), 0)
        text = self._text(CONTROLLER)
        self.assertIn("swarm:", text)
        self.assertNotIn("data:", text)

    def test_an_endpoint_replaces_the_hostname_peers_dial(self):
        argv = self._argv("--endpoint", "swarm-mgr-01=192.168.244.10")
        self.assertEqual(main(argv), 0)
        text = self._text("swarm-wrk-01")
        self.assertIn("endpoint: 192.168.244.10", text)
        self.assertIn("host: swarm-mgr-01", text)

    def test_a_host_without_an_endpoint_is_dialled_by_name(self):
        self.assertEqual(main(self._argv()), 0)
        self.assertIn("endpoint: swarm-mgr-01", self._text("swarm-wrk-01"))

    def test_a_malformed_endpoint_aborts(self):
        with self.assertRaises(SystemExit):
            main(self._argv("--endpoint", "swarm-mgr-01"))

    def test_a_rerun_keeps_the_controller_key_too(self):
        argv = self._argv("--controller", CONTROLLER, "--controller-mesh", "swarm")
        self.assertEqual(main(argv), 0)
        before = self._text(CONTROLLER)

        self.assertEqual(main(argv), 0)
        self.assertEqual(self._text(CONTROLLER), before)

    def test_a_rotation_gives_a_host_one_key_across_every_mesh(self):
        self.assertEqual(main(self._argv()), 0)
        self.assertEqual(main(self._argv("--rotate")), 0)

        hub = self._text("swarm-mgr-01")
        own = re.findall(r"^        public_key: (\S+)$", hub, re.MULTILINE)
        spoke_peers = re.findall(
            r"^          public_key: (\S+)$", self._text("swarm-wrk-01"), re.MULTILINE
        )

        self.assertEqual(2, len(own))
        self.assertEqual(1, len(set(own)))
        self.assertIn(own[0], spoke_peers)

    def _address(self, host: str, mesh_name: str) -> str:
        document = load_yaml_any(str(self.host_vars / f"{host}.yml"))
        return document["applications"]["svc-net-wireguard"]["meshes"][mesh_name][
            "address"
        ]

    def test_growing_the_cluster_leaves_every_member_on_its_address(self):
        """A node added later must not renumber the nodes already up.

        `wg syncconf` never moves a live interface's address, so a renumbered
        member answers on the old one while the inventory has moved to the
        new one -- and the next pass cannot reach it.
        """
        self.assertEqual(main(self._argv()), 0)
        before = {host: self._address(host, "swarm") for host in SWARM_HOSTS}

        (self.host_vars / "alpha-wrk-00.yml").write_text("---\n", encoding="utf-8")
        self.cluster.write_text(
            CLUSTER_INVENTORY.replace(
                "        swarm-wrk-01: {}",
                "        alpha-wrk-00: {}\n        swarm-wrk-01: {}",
            ),
            encoding="utf-8",
        )
        self.assertEqual(main(self._argv()), 0)

        for host, address in before.items():
            with self.subTest(host=host):
                self.assertEqual(self._address(host, "swarm"), address)
        self.assertNotIn(self._address("alpha-wrk-00", "swarm"), set(before.values()))

    def test_a_rotation_leaves_every_member_on_its_address(self):
        self.assertEqual(main(self._argv()), 0)
        before = {host: self._address(host, "swarm") for host in SWARM_HOSTS}
        self.assertEqual(main(self._argv("--rotate")), 0)
        for host, address in before.items():
            with self.subTest(host=host):
                self.assertEqual(self._address(host, "swarm"), address)

    def test_a_rerun_is_a_no_op(self):
        self.assertEqual(main(self._argv()), 0)
        before = {host: self._text(host) for host in HOSTS}
        self.assertEqual(main(self._argv()), 0)
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(self._text(host), before[host])
