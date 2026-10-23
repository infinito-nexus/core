from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import Any, ClassVar

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = Path(PROJECT_ROOT) / "roles" / "svc-net-wireguard"

HUB_PEER = {
    "host": "galaxy",
    "endpoint": "vpn.example.org",
    "public_key": "key-galaxy",
    "address": "10.0.0.1",
    "allowed_ips": "10.0.0.0/24",
    "is_hub": True,
}
FIXED_SPOKE = {
    "host": "echo-srv",
    "endpoint": "echo-srv",
    "public_key": "key-echo",
    "address": "10.0.0.11",
    "allowed_ips": "10.0.0.11/32",
    "is_hub": False,
}
ROAMING_SPOKE = {
    "host": "laptop",
    "public_key": "key-laptop",
    "address": "10.0.0.5",
    "allowed_ips": "10.0.0.5/32",
    "is_hub": False,
}

HUB = {
    "name": "wg0",
    "host": "galaxy",
    "address": "10.0.0.1",
    "subnet": "10.0.0.0/24",
    "listen_port": 51871,
    "is_hub": True,
    "peers": [FIXED_SPOKE, ROAMING_SPOKE],
}
ROAMER = {
    "name": "wg0",
    "host": "laptop",
    "address": "10.0.0.5",
    "subnet": "10.0.0.0/24",
    "listen_port": 51871,
    "is_hub": False,
    "peers": [HUB_PEER],
}
FULL_MEMBER = {
    "name": "alpha",
    "host": "host-1",
    "address": "10.100.200.11",
    "subnet": "10.100.200.0/24",
    "listen_port": 51900,
    "is_hub": False,
    "peers": [
        {**FIXED_SPOKE, "host": "host-2", "endpoint": "host-2", "public_key": "k2"},
        {**FIXED_SPOKE, "host": "host-3", "endpoint": "host-3", "public_key": "k3"},
    ],
}


def _filters() -> dict:
    spec = importlib.util.spec_from_file_location(
        "mesh_peers_plugin", ROLE / "filter_plugins" / "mesh_peers.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def render_interface(mesh: dict) -> str:
    """The wg-quick file the role renders for one interface.

    Args:
        mesh: one entry of ``networks.interfaces``.
    """
    env = Environment(
        loader=FileSystemLoader(str(ROLE / "templates")),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )
    env.filters.update(_filters())
    return env.get_template("wg.conf.j2").render(
        mesh=mesh, WIREGUARD_PRIVATE_KEY="private-key-stub", wireguard_mtu=1360
    )


def _peer_blocks(rendered: str) -> dict[str, str]:
    blocks = rendered.split("[Peer]")[1:]
    return {
        next(
            line.split("=", 1)[1].strip()
            for line in block.splitlines()
            if line.startswith("PublicKey")
        ): block
        for block in blocks
    }


class TestTheComposeHub(unittest.TestCase):
    def setUp(self):
        self.rendered = render_interface(HUB)

    def test_it_listens_on_the_chosen_port(self):
        self.assertIn("ListenPort = 51871", self.rendered)

    def test_it_dials_no_spoke(self):
        self.assertNotIn("Endpoint", self.rendered)
        self.assertNotIn("PersistentKeepalive", self.rendered)

    def test_it_pins_every_spoke_to_its_own_address(self):
        peers = _peer_blocks(self.rendered)
        self.assertIn("AllowedIPs = 10.0.0.11/32", peers["key-echo"])
        self.assertIn("AllowedIPs = 10.0.0.5/32", peers["key-laptop"])


class TestTheRoamingSpoke(unittest.TestCase):
    def setUp(self):
        self.rendered = render_interface(ROAMER)

    def test_it_does_not_listen(self):
        self.assertNotIn("ListenPort", self.rendered)

    def test_it_dials_the_hub_on_the_mesh_port(self):
        self.assertIn("Endpoint = vpn.example.org:51871", self.rendered)

    def test_it_keeps_the_path_open_from_behind_nat(self):
        self.assertIn("PersistentKeepalive = 25", self.rendered)

    def test_it_routes_the_whole_subnet_through_the_hub(self):
        self.assertIn("AllowedIPs = 10.0.0.0/24", self.rendered)


class TestTheFullMeshMember(unittest.TestCase):
    def setUp(self):
        self.rendered = render_interface(FULL_MEMBER)

    def test_it_listens(self):
        self.assertIn("ListenPort = 51900", self.rendered)

    def test_it_dials_every_peer(self):
        peers = _peer_blocks(self.rendered)
        self.assertIn("Endpoint = host-2:51900", peers["k2"])
        self.assertIn("Endpoint = host-3:51900", peers["k3"])


class TestTheGateWiring(unittest.TestCase):
    VARS: ClassVar[dict]

    @classmethod
    def setUpClass(cls):
        cls.VARS = load_yaml(ROLE / ROLE_FILE_VARS_MAIN)

    def _awaited(self, groups: list[str], meshes: dict) -> dict:
        env = NativeEnvironment(undefined=StrictUndefined)
        env.filters.update(_filters())
        env.filters["bool"] = _as_bool
        manager = env.from_string(self.VARS["WIREGUARD_SWARM_MANAGER"]).render(
            group_names=groups
        )
        return env.from_string(self.VARS["WIREGUARD_AWAITED_KEYS"]).render(
            WIREGUARD_ACTIVE_MESHES=meshes, WIREGUARD_SWARM_MANAGER=manager
        )

    def test_a_named_hub_waits_for_its_fixed_spokes_only(self):
        self.assertEqual(
            {"wg0": ["key-echo"]}, self._awaited(["svc-net-wireguard"], {"wg0": HUB})
        )

    def test_the_swarm_manager_waits_for_no_spoke(self):
        groups = ["svc-swarm-manager", "svc-swarm-node", "svc-net-wireguard"]
        self.assertEqual({}, self._awaited(groups, {"wg0": HUB}))

    def test_a_roaming_spoke_waits_for_the_hub_alone(self):
        self.assertEqual(
            {"wg0": ["key-galaxy"]},
            self._awaited(["svc-net-wireguard"], {"wg0": ROAMER}),
        )

    def test_a_full_mesh_member_waits_for_every_peer(self):
        self.assertEqual(
            {"alpha": ["k2", "k3"]},
            self._awaited(["svc-net-wireguard"], {"alpha": FULL_MEMBER}),
        )
