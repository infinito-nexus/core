import unittest

from utils.networks.mesh import (
    REJECT_AFTER_TIME,
    awaited_keys,
    awaited_peers,
    dialled_peers,
    handshaken,
    is_full,
    listens,
    underlay,
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


class TestUnderlay(unittest.TestCase):
    DUAL_STACK = (
        "178.63.190.220  STREAM veen.world\n"
        "178.63.190.220  DGRAM  \n"
        "178.63.190.220  RAW    \n"
    )

    def test_a_dual_stack_name_dials_its_ipv4_address(self):
        self.assertEqual(
            {"veen.world": "178.63.190.220"},
            underlay([{"endpoint": "veen.world", "stdout": self.DUAL_STACK}]),
        )

    def test_the_first_of_several_a_records_wins(self):
        state = "192.0.2.1       STREAM hub\n192.0.2.1       DGRAM  \n192.0.2.2       STREAM \n"
        self.assertEqual(
            {"hub": "192.0.2.1"}, underlay([{"endpoint": "hub", "stdout": state}])
        )

    def test_an_ipv4_literal_dials_itself(self):
        state = "192.0.2.10      STREAM 192.0.2.10\n"
        self.assertEqual(
            {"192.0.2.10": "192.0.2.10"},
            underlay([{"endpoint": "192.0.2.10", "stdout": state}]),
        )

    def test_a_name_without_an_ipv4_answer_is_left_out(self):
        self.assertEqual({}, underlay([{"endpoint": "v6only.example", "stdout": ""}]))

    def test_an_unparsable_answer_is_left_out(self):
        state = "<invalid>       STREAM hub\n"
        self.assertEqual({}, underlay([{"endpoint": "hub", "stdout": state}]))

    def test_an_ipv6_answer_never_becomes_an_endpoint(self):
        state = "2a01:4f8:2201:4695::2 STREAM veen.world\n"
        self.assertEqual({}, underlay([{"endpoint": "veen.world", "stdout": state}]))

    def test_every_endpoint_maps_to_its_own_address(self):
        self.assertEqual(
            {"mgr": "192.0.2.1", "nfs": "192.0.2.3"},
            underlay(
                [
                    {"endpoint": "mgr", "stdout": "192.0.2.1 STREAM mgr\n"},
                    {"endpoint": "nfs", "stdout": "192.0.2.3 STREAM nfs\n"},
                ]
            ),
        )

    def test_no_dialled_endpoint_resolves_to_nothing(self):
        self.assertEqual({}, underlay([]))


class TestHandshaken(unittest.TestCase):
    NOW = 1760000100
    STATE = f"{NOW}\nkey-wrk\t1760000000\nkey-nfs\t0\nkey-mgr\t1760000005\n"

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

    def test_a_handshake_as_old_as_the_session_lifetime_passes(self):
        stamp = self.NOW - REJECT_AFTER_TIME
        self.assertTrue(handshaken(f"{self.NOW}\nkey-mgr\t{stamp}", ["key-mgr"]))

    def test_a_handshake_older_than_the_session_lifetime_fails(self):
        stamp = self.NOW - REJECT_AFTER_TIME - 1
        self.assertFalse(handshaken(f"{self.NOW}\nkey-mgr\t{stamp}", ["key-mgr"]))

    def test_a_handshake_left_from_an_hour_ago_fails(self):
        self.assertFalse(handshaken("1793545708\nkey-mgr\t1793542108", ["key-mgr"]))

    def test_a_handshake_stamped_ahead_of_a_stepped_back_clock_fails(self):
        stamp = self.NOW + REJECT_AFTER_TIME + 1
        self.assertFalse(handshaken(f"{self.NOW}\nkey-mgr\t{stamp}", ["key-mgr"]))

    def test_a_state_without_the_host_epoch_fails(self):
        self.assertFalse(handshaken("key-mgr\t1760000005", ["key-mgr"]))
