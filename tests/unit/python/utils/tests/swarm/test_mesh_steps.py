from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.tests.swarm import mesh as mesh_steps

MESH = """\
applications:
  svc-net-wireguard:
    meshes:
      swarm:
        host: {host}
        address: {address}
"""


class TestSwitchToMeshTransport(unittest.TestCase):
    def _inventory(self, td: str) -> Path:
        host_vars = Path(td) / "host_vars"
        host_vars.mkdir()
        for host, address in (
            ("web-app-openbao-swarm-mgr-01", "10.100.0.1"),
            ("web-app-openbao-swarm-wrk-01", "10.100.0.12"),
            ("localhost", "10.100.0.11"),
        ):
            (host_vars / f"{host}.yml").write_text(
                MESH.format(host=host, address=address), encoding="utf-8"
            )
        return host_vars

    def _run(self, td: str) -> int:
        env = {"INFINITO_SWARM_VPN": "true", "KEY_PATH": str(Path(td) / "admin.key")}
        with mock.patch.dict("os.environ", env, clear=False):
            return mesh_steps.switch_to_mesh_transport(inv_dir=td)

    def test_a_node_is_pointed_at_its_mesh_address(self):
        with tempfile.TemporaryDirectory() as td:
            host_vars = self._inventory(td)
            self.assertEqual(self._run(td), 0)
            doc = load_yaml_any(str(host_vars / "web-app-openbao-swarm-wrk-01.yml"))

        self.assertEqual(doc["ansible_host"], "10.100.0.12")
        self.assertEqual(doc["ansible_connection"], "ssh")

    def test_the_controller_keeps_its_own_transport(self):
        with tempfile.TemporaryDirectory() as td:
            host_vars = self._inventory(td)
            self.assertEqual(self._run(td), 0)
            doc = load_yaml_any(str(host_vars / "localhost.yml"))

        self.assertNotIn("ansible_connection", doc)
        self.assertNotIn("ansible_host", doc)


if __name__ == "__main__":
    unittest.main()
