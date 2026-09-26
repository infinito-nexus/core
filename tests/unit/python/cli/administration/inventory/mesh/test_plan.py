"""Planning guarantees for cross-host mesh credentials.

Planning is the whole correctness argument for the mesh, and every failure mode
here is silent at deploy time: a spoke missing from the hub's peer list is a
host that configures cleanly and never handshakes, and a public key that does
not answer for its private half looks identical until traffic is attempted.
"""

from __future__ import annotations

import unittest

from cli.administration.inventory.mesh.inventory import assert_no_subnet_overlap
from cli.administration.inventory.mesh.keys import (
    generate_private_key,
    is_valid_public_key,
    public_key_of,
)
from cli.administration.inventory.mesh.model import MeshSpec
from cli.administration.inventory.mesh.plan import plan_mesh

SWARM = MeshSpec(
    name="swarm",
    hub_group="svc-swarm-manager",
    spoke_groups=("svc-swarm-node",),
    subnet="10.100.0.0/24",
    listen_port=51820,
)

DATA = MeshSpec(
    name="data",
    hub_group="svc-swarm-manager",
    spoke_groups=("svc-storage-nfs-server",),
    subnet="10.100.1.0/24",
    listen_port=51821,
    spoke_group_prefixes=("svc-bkp-",),
)

GROUPS = {
    "svc-swarm-manager": ["swarm-mgr-01"],
    "svc-swarm-node": ["swarm-mgr-01", "swarm-wrk-01", "swarm-wrk-02"],
    "svc-storage-nfs-server": ["nfs-server"],
    "svc-bkp-remote-2-local": ["swarm-bkp-01"],
    "svc-bkp-local-2-device": ["swarm-bkp-01"],
}


class TestMembership(unittest.TestCase):
    def test_the_hub_is_not_also_listed_as_its_own_spoke(self):
        """The manager is a member of svc-swarm-node as well as the hub group.

        Left unfiltered it peers with itself, which WireGuard accepts and which
        then routes the hub's own traffic into its own tunnel.
        """
        mesh = plan_mesh(SWARM, GROUPS)
        self.assertEqual(mesh.hub.host, "swarm-mgr-01")
        self.assertNotIn("swarm-mgr-01", [s.host for s in mesh.spokes])
        self.assertEqual(
            [s.host for s in mesh.spokes], ["swarm-wrk-01", "swarm-wrk-02"]
        )

    def test_a_group_prefix_admits_the_backup_host_once(self):
        mesh = plan_mesh(DATA, GROUPS)
        self.assertEqual([s.host for s in mesh.spokes], ["nfs-server", "swarm-bkp-01"])

    def test_a_hub_group_without_exactly_one_host_is_refused(self):
        for hosts in ([], ["a", "b"]):
            with self.subTest(hosts=hosts), self.assertRaises(ValueError):
                plan_mesh(SWARM, {**GROUPS, "svc-swarm-manager": hosts})

    def test_membership_is_stable_against_inventory_ordering(self):
        shuffled = {**GROUPS, "svc-swarm-node": ["swarm-wrk-02", "swarm-wrk-01"]}
        self.assertEqual(
            [m.address for m in plan_mesh(SWARM, GROUPS).members],
            [m.address for m in plan_mesh(SWARM, shuffled).members],
        )


class TestAddressing(unittest.TestCase):
    def test_every_member_is_addressed_inside_the_mesh_subnet(self):
        for spec in (SWARM, DATA):
            with self.subTest(mesh=spec.name):
                mesh = plan_mesh(spec, GROUPS)
                prefix = spec.subnet.rsplit(".", 1)[0]
                for member in mesh.members:
                    self.assertTrue(member.address.startswith(prefix + "."))

    def test_no_two_members_share_an_address(self):
        mesh = plan_mesh(SWARM, GROUPS)
        addresses = [m.address for m in mesh.members]
        self.assertEqual(len(addresses), len(set(addresses)))

    def test_the_two_meshes_do_not_share_an_address(self):
        swarm = {m.address for m in plan_mesh(SWARM, GROUPS).members}
        data = {m.address for m in plan_mesh(DATA, GROUPS).members}
        self.assertEqual(swarm & data, set())


class TestPeering(unittest.TestCase):
    def test_the_hub_peers_with_every_spoke(self):
        mesh = plan_mesh(SWARM, GROUPS)
        self.assertEqual(
            {p.host for p in mesh.peers_of(mesh.hub.host)},
            {s.host for s in mesh.spokes},
        )

    def test_a_spoke_peers_only_with_the_hub(self):
        mesh = plan_mesh(SWARM, GROUPS)
        for spoke in mesh.spokes:
            with self.subTest(spoke=spoke.host):
                peers = mesh.peers_of(spoke.host)
                self.assertEqual([p.host for p in peers], [mesh.hub.host])

    def test_a_host_outside_the_mesh_has_no_peers(self):
        mesh = plan_mesh(SWARM, GROUPS)
        self.assertEqual(mesh.peers_of("nfs-server"), ())


class TestKeyPairing(unittest.TestCase):
    def test_every_public_key_answers_for_its_private_key(self):
        mesh = plan_mesh(SWARM, GROUPS)
        for member in mesh.members:
            with self.subTest(host=member.host):
                self.assertIsNotNone(member.private_key)
                self.assertEqual(public_key_of(member.private_key), member.public_key)

    def test_no_two_members_share_a_keypair(self):
        mesh = plan_mesh(SWARM, GROUPS)
        self.assertEqual(len({m.private_key for m in mesh.members}), len(mesh.members))

    def test_a_peer_entry_never_carries_a_private_key(self):
        """The containment guarantee the whole mesh rests on.

        A peer is described by its public half only, so one host's inventory can
        never be used to impersonate another.
        """
        mesh = plan_mesh(SWARM, GROUPS)
        secrets = {m.private_key for m in mesh.members}
        for member in mesh.members:
            for peer in mesh.peers_of(member.host):
                with self.subTest(host=member.host, peer=peer.host):
                    self.assertNotIn(peer.public_key, secrets)
                    self.assertTrue(is_valid_public_key(peer.public_key))

    def test_a_malformed_private_key_is_refused(self):
        for bad in ("", "not-base64!", "c2hvcnQ="):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                public_key_of(bad)


class TestRotation(unittest.TestCase):
    def test_an_existing_member_keeps_its_key_and_is_not_rewritten(self):
        """Vault encryption is salted.

        Re-encrypting an unchanged secret would rewrite the file on every run,
        so a member that already holds a key carries no private half and the
        writer leaves its stored credential alone.
        """
        held = {"swarm-wrk-01": public_key_of(generate_private_key())}
        mesh = plan_mesh(SWARM, GROUPS, held)
        member = mesh.member("swarm-wrk-01")
        self.assertEqual(member.public_key, held["swarm-wrk-01"])
        self.assertIsNone(member.private_key)

    def test_a_new_member_is_keyed_while_the_others_are_untouched(self):
        held = {
            host: public_key_of(generate_private_key())
            for host in ("swarm-mgr-01", "swarm-wrk-01")
        }
        mesh = plan_mesh(SWARM, GROUPS, held)
        self.assertIsNone(mesh.member("swarm-wrk-01").private_key)
        self.assertIsNotNone(mesh.member("swarm-wrk-02").private_key)

    def test_rotation_replaces_every_key_including_held_ones(self):
        held = {
            host: public_key_of(generate_private_key())
            for host in ("swarm-mgr-01", "swarm-wrk-01", "swarm-wrk-02")
        }
        mesh = plan_mesh(SWARM, GROUPS, held, rotate=True)
        for member in mesh.members:
            with self.subTest(host=member.host):
                self.assertIsNotNone(member.private_key)
                self.assertNotEqual(member.public_key, held[member.host])

    def test_rotation_keeps_the_mesh_internally_consistent(self):
        """Every peer list must carry the rotated key, not the previous one.

        A partial rotation is the failure that partitions the mesh: the hub
        holds a spoke's old public key, the spoke presents a new one, and the
        handshake is refused with nothing logged on either side.
        """
        mesh = plan_mesh(SWARM, GROUPS, rotate=True)
        published = {m.host: m.public_key for m in mesh.members}
        for member in mesh.members:
            for peer in mesh.peers_of(member.host):
                with self.subTest(host=member.host, peer=peer.host):
                    self.assertEqual(peer.public_key, published[peer.host])


class TestSubnetGuards(unittest.TestCase):
    def test_overlapping_meshes_are_refused(self):
        clash = MeshSpec(
            name="clash",
            hub_group="svc-swarm-manager",
            spoke_groups=(),
            subnet="10.100.0.0/25",
            listen_port=51822,
        )
        with self.assertRaises(ValueError):
            assert_no_subnet_overlap([SWARM, clash], "10.100.0.0/16")

    def test_a_subnet_outside_the_pool_is_refused(self):
        """192.168.244.0/24 is the swarm lab underlay.

        A mesh allocated there would collide with the addresses it is supposed
        to tunnel over.
        """
        escapee = MeshSpec(
            name="escapee",
            hub_group="svc-swarm-manager",
            spoke_groups=(),
            subnet="192.168.244.0/24",
            listen_port=51823,
        )
        with self.assertRaises(ValueError):
            assert_no_subnet_overlap([escapee], "10.100.0.0/16")

    def test_a_shared_listen_port_is_refused(self):
        twin = MeshSpec(
            name="twin",
            hub_group="svc-swarm-manager",
            spoke_groups=(),
            subnet="10.100.9.0/24",
            listen_port=SWARM.listen_port,
        )
        with self.assertRaises(ValueError):
            assert_no_subnet_overlap([SWARM, twin], "10.100.0.0/16")

    def test_the_declared_meshes_pass_their_own_guards(self):
        assert_no_subnet_overlap([SWARM, DATA], "10.100.0.0/16")
