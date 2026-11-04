from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TEST_DIR = Path(PROJECT_ROOT) / "roles" / "svc-net-wireguard" / "files" / "test"
MESH_ROLE = "svc-bkp-remote-2-local"
HOSTS = {"I": "wg-1", "II": "wg-2", "III": "wg-3"}


def _module():
    spec = importlib.util.spec_from_file_location(
        "wireguard_cli_test_inventory", TEST_DIR / "inventory.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LayoutOnDisk(unittest.TestCase):
    LAYOUT = "layout.yml"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name)
        pairs = [f"{member}={host}" for member, host in HOSTS.items()]
        argv = [str(TEST_DIR / self.LAYOUT), str(self.work), MESH_ROLE, *pairs]
        self.assertEqual(0, _module().main(argv))

    def _own(self, host: str) -> dict:
        document = load_yaml_any(str(self.work / "host_vars" / f"{host}.yml"))
        return document["applications"]["svc-net-wireguard"]["networks"]


class TestTheFullMeshLayout(LayoutOnDisk, unittest.TestCase):
    def test_no_host_names_a_hub(self):
        for host in HOSTS.values():
            with self.subTest(host=host):
                self.assertNotIn("hub", self._own(host))

    def test_no_host_roams(self):
        for host in HOSTS.values():
            with self.subTest(host=host):
                self.assertNotIn("roaming", self._own(host))


class TestTheHubLayout(LayoutOnDisk, unittest.TestCase):
    LAYOUT = "layout-hub.yml"

    def test_every_host_names_the_container_playing_the_hub(self):
        for host in HOSTS.values():
            with self.subTest(host=host):
                self.assertEqual(HOSTS["I"], self._own(host)["hub"])

    def test_only_the_marked_member_roams(self):
        self.assertTrue(self._own(HOSTS["II"])["roaming"])
        self.assertNotIn("roaming", self._own(HOSTS["III"]))
        self.assertNotIn("roaming", self._own(HOSTS["I"]))

    def test_the_spokes_join_through_the_mesh_role(self):
        document = load_yaml_any(str(self.work / "host_vars" / f"{HOSTS['III']}.yml"))
        self.assertEqual(
            ["gamma"], document["applications"][MESH_ROLE]["networks"]["meshes"]
        )
