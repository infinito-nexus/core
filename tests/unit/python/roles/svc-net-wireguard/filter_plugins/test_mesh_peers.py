import importlib.util
import unittest

from utils.networks.mesh import awaited_keys, dialled_peers, handshaken, listens

from . import PROJECT_ROOT

PLUGIN = (
    PROJECT_ROOT / "roles" / "svc-net-wireguard" / "filter_plugins" / "mesh_peers.py"
)


def _filters() -> dict:
    spec = importlib.util.spec_from_file_location("mesh_peers_plugin", PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


class TestMeshPeersFilters(unittest.TestCase):
    def test_the_filters_are_the_mesh_spot_functions(self):
        self.assertEqual(
            {
                "mesh_awaited_keys": awaited_keys,
                "mesh_dialled_peers": dialled_peers,
                "mesh_handshaken": handshaken,
                "mesh_listens": listens,
            },
            _filters(),
        )
