import unittest

from utils.networks.mesh import (
    awaited_keys,
    awaited_peers,
    dialled_peers,
    handshaken,
    is_full,
    listens,
)

HUB_PEER = {
    "host": "mgr",
    "endpoint": "mgr",
    "public_key": "key-mgr",
    "address": "10.100.0.1",
    "is_hub": True,
}
SPOKE_PEER = {
    "host": "wrk",
    "endpoint": "wrk",
    "public_key": "key-wrk",
    "address": "10.100.0.11",
    "is_hub": False,
}
OTHER_PEER = {
    "host": "nfs",
    "endpoint": "nfs",
    "public_key": "key-nfs",
    "address": "10.100.0.12",
    "is_hub": False,
}
ROAMING_PEER = {
    "host": "laptop",
    "public_key": "key-laptop",
    "address": "10.100.0.13",
    "is_hub": False,
}

HUB = {"name": "swarm", "is_hub": True, "peers": [SPOKE_PEER, OTHER_PEER]}
SPOKE = {"name": "swarm", "is_hub": False, "peers": [HUB_PEER]}
FULL = {"name": "alpha", "is_hub": False, "peers": [SPOKE_PEER, OTHER_PEER]}
COMPOSE_HUB = {
    "name": "wg0",
    "is_hub": True,
    "peers": [SPOKE_PEER, ROAMING_PEER, OTHER_PEER],
}


class TestHubAndSpoke(unittest.TestCase):
    def test_only_the_hub_listens(self):
        self.assertTrue(listens(HUB))
        self.assertFalse(listens(SPOKE))

    def test_a_spoke_dials_its_hub_alone(self):
        self.assertEqual([HUB_PEER], dialled_peers(SPOKE))

    def test_the_hub_dials_nobody(self):
        self.assertEqual([], dialled_peers(HUB))

    def test_neither_is_a_full_mesh(self):
        self.assertFalse(is_full(HUB))
        self.assertFalse(is_full(SPOKE))


class TestFullMesh(unittest.TestCase):
    def test_a_member_listens(self):
        self.assertTrue(is_full(FULL))
        self.assertTrue(listens(FULL))

    def test_a_member_dials_every_peer(self):
        self.assertEqual([SPOKE_PEER, OTHER_PEER], dialled_peers(FULL))

    def test_a_malformed_peer_list_dials_nobody(self):
        self.assertEqual([], dialled_peers({"is_hub": False, "peers": "mgr"}))


class TestAwaitedPeers(unittest.TestCase):
    def test_a_spoke_awaits_its_hub_alone(self):
        self.assertEqual([HUB_PEER], awaited_peers(SPOKE, swarm_manager=False))

    def test_a_full_mesh_member_awaits_every_peer(self):
        self.assertEqual(
            [SPOKE_PEER, OTHER_PEER], awaited_peers(FULL, swarm_manager=False)
        )

    def test_a_named_hub_awaits_every_spoke_with_an_endpoint(self):
        self.assertEqual(
            [SPOKE_PEER, OTHER_PEER], awaited_peers(COMPOSE_HUB, swarm_manager=False)
        )

    def test_a_named_hub_skips_a_roaming_spoke(self):
        self.assertNotIn(ROAMING_PEER, awaited_peers(COMPOSE_HUB, swarm_manager=False))

    def test_the_swarm_manager_awaits_no_spoke(self):
        self.assertEqual([], awaited_peers(HUB, swarm_manager=True))


class TestAwaitedKeys(unittest.TestCase):
    def test_every_mesh_maps_to_the_keys_it_awaits(self):
        self.assertEqual(
            {"alpha": ["key-wrk", "key-nfs"], "swarm": ["key-mgr"]},
            awaited_keys({"swarm": SPOKE, "alpha": FULL}, swarm_manager=False),
        )

    def test_a_mesh_awaiting_nobody_is_left_out(self):
        self.assertEqual({}, awaited_keys({"swarm": HUB}, swarm_manager=True))

    def test_a_hub_of_only_roaming_spokes_awaits_nobody(self):
        lonely = {"name": "wg0", "is_hub": True, "peers": [ROAMING_PEER]}
        self.assertEqual({}, awaited_keys({"wg0": lonely}, swarm_manager=False))


class TestHandshaken(unittest.TestCase):
    STATE = "key-wrk\t1760000000\nkey-nfs\t0\nkey-mgr\t1760000005\n"

    def test_keys_that_handshaked_pass(self):
        self.assertTrue(handshaken(self.STATE, ["key-wrk", "key-mgr"]))

    def test_a_key_that_never_handshaked_fails(self):
        self.assertFalse(handshaken(self.STATE, ["key-wrk", "key-nfs"]))

    def test_a_key_the_interface_does_not_carry_fails(self):
        self.assertFalse(handshaken(self.STATE, ["key-absent"]))

    def test_a_skipped_peer_may_stay_silent(self):
        self.assertTrue(handshaken(self.STATE, ["key-mgr"]))

    def test_an_interface_without_output_fails(self):
        self.assertFalse(handshaken("", ["key-mgr"]))
