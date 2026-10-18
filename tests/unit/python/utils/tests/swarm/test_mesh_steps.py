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
    networks:
      interfaces:
        - name: swarm
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
        env = {
            "INFINITO_SWARM_VPN": "true",
            "INFINITO_SWARM_MESHES": "",
            "KEY_PATH": str(Path(td) / "admin.key"),
        }
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


EXAMPLE = "inventories/examples/wireguard-three-meshes/wireguard.yml"


class TestLayout(unittest.TestCase):
    def _env(self, meshes: str):
        return mock.patch.dict(
            "os.environ",
            {"INFINITO_SWARM_VPN": "true", "INFINITO_SWARM_MESHES": meshes},
            clear=False,
        )

    def test_an_unset_choice_deploys_the_development_meshes(self):
        with self._env(""):
            self.assertEqual(mesh_steps.transport_mesh(), "swarm")

    def test_an_example_moves_the_transport_onto_its_first_mesh(self):
        with self._env(EXAMPLE):
            self.assertEqual(mesh_steps.transport_mesh(), "alpha")

    def test_the_layout_is_handed_over_as_inventory_values(self):
        with self._env(EXAMPLE):
            applications = mesh_steps.layout_applications()
        self.assertEqual(
            ["alpha", "beta", "gamma"],
            [
                mesh["name"]
                for mesh in applications["svc-net-wireguard"]["networks"]["meshes"]
            ],
        )
        self.assertEqual(
            ["alpha"], applications["svc-swarm-node"]["networks"]["meshes"]
        )

    def test_the_writer_reads_the_meshes_from_the_inventory(self):
        with (
            self._env(EXAMPLE),
            mock.patch.object(mesh_steps, "run_step", return_value=0) as step,
        ):
            self.assertEqual(mesh_steps.write_mesh(inv_dir="/tmp/inv"), 0)
        argv = step.call_args.args[0]
        self.assertNotIn("--group-vars-file", argv)
        self.assertEqual(argv[argv.index("--controller-mesh") + 1], "alpha")


LINKS = """[
  {"ifname": "alpha", "addr_info": [{"local": "10.100.10.11", "prefixlen": 24}]},
  {"ifname": "swarm", "addr_info": [{"local": "10.100.0.11", "prefixlen": 24}]},
  {"ifname": "wg0", "addr_info": [{"local": "10.8.0.2", "prefixlen": 24}]}
]"""


class TestStaleControllerInterfaces(unittest.TestCase):
    def _stale(self) -> list[str]:
        listed = mock.Mock(stdout=LINKS)
        with (
            mock.patch.dict("os.environ", {"INFINITO_SWARM_MESHES": ""}, clear=False),
            mock.patch.object(mesh_steps.subprocess, "run", return_value=listed),
        ):
            return mesh_steps.stale_controller_interfaces()

    def test_a_pool_link_no_declaration_names_is_stale(self):
        self.assertIn("alpha", self._stale())

    def test_a_declared_mesh_is_kept(self):
        self.assertNotIn("swarm", self._stale())

    def test_a_link_outside_the_pool_is_not_the_harness_to_remove(self):
        self.assertNotIn("wg0", self._stale())

    def test_the_stale_link_goes_before_the_controller_joins(self):
        calls: list[list[str]] = []
        with (
            tempfile.TemporaryDirectory() as td,
            mock.patch.dict("os.environ", {"INFINITO_SWARM_VPN": "true"}, clear=False),
            mock.patch.object(
                mesh_steps, "stale_controller_interfaces", return_value=["alpha"]
            ),
            mock.patch.object(
                mesh_steps,
                "run_step",
                side_effect=lambda cmd, **_: calls.append(cmd) or 0,
            ),
        ):
            self.assertEqual(mesh_steps.mesh_controller(inv_dir=td), 0)
        self.assertEqual(calls[0][-4:], ["ip", "link", "delete", "alpha"])
        self.assertEqual(calls[1][0], "ansible-playbook")


if __name__ == "__main__":
    unittest.main()
