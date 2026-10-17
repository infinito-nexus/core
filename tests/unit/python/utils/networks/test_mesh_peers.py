import unittest

from utils.networks.mesh import dialled_peers, is_full, listens

HUB_PEER = {"host": "mgr", "address": "10.100.0.1", "is_hub": True}
SPOKE_PEER = {"host": "wrk", "address": "10.100.0.11", "is_hub": False}
OTHER_PEER = {"host": "nfs", "address": "10.100.0.12", "is_hub": False}

HUB = {"name": "swarm", "is_hub": True, "peers": [SPOKE_PEER, OTHER_PEER]}
SPOKE = {"name": "swarm", "is_hub": False, "peers": [HUB_PEER]}
FULL = {"name": "alpha", "is_hub": False, "peers": [SPOKE_PEER, OTHER_PEER]}


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
