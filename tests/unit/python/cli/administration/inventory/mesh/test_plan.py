from __future__ import annotations

import unittest

from cli.administration.inventory.mesh.inventory import assert_no_subnet_overlap
from cli.administration.inventory.mesh.keys import (
    generate_private_key,
    is_valid_public_key,
    public_key_of,
)
from cli.administration.inventory.mesh.model import MeshSpec, Topology
from cli.administration.inventory.mesh.plan import plan_mesh, primary_meshes

SWARM = MeshSpec(name="swarm", subnet="10.100.0.0/24", listen_port=51820)

DATA = MeshSpec(name="data", subnet="10.100.1.0/24", listen_port=51821)

TOPOLOGY = Topology(
    hub="swarm-mgr-01",
    spokes={
        "swarm": ("swarm-wrk-01", "swarm-wrk-02"),
        "data": ("nfs-server", "swarm-bkp-01"),
    },
)


def _with_spokes(**spokes: tuple[str, ...]) -> Topology:
    return Topology(hub=TOPOLOGY.hub, spokes={**TOPOLOGY.spokes, **spokes})


class TestMembership(unittest.TestCase):
    def test_the_hub_is_not_also_listed_as_its_own_spoke(self):
        mesh = plan_mesh(SWARM, _with_spokes(swarm=("swarm-mgr-01", "swarm-wrk-01")))
        self.assertEqual(mesh.hub.host, "swarm-mgr-01")
        self.assertEqual([s.host for s in mesh.spokes], ["swarm-wrk-01"])

    def test_a_host_two_roles_put_into_one_mesh_is_one_spoke(self):
        topology = _with_spokes(data=("nfs-server", "swarm-bkp-01", "nfs-server"))
        mesh = plan_mesh(DATA, topology)
        self.assertEqual([s.host for s in mesh.spokes], ["nfs-server", "swarm-bkp-01"])

    def test_membership_is_stable_against_inventory_ordering(self):
        shuffled = _with_spokes(swarm=("swarm-wrk-02", "swarm-wrk-01"))
        self.assertEqual(
            [m.address for m in plan_mesh(SWARM, TOPOLOGY).members],
            [m.address for m in plan_mesh(SWARM, shuffled).members],
        )


class TestAddressing(unittest.TestCase):
    def test_every_member_is_addressed_inside_the_mesh_subnet(self):
        for spec in (SWARM, DATA):
            with self.subTest(mesh=spec.name):
                mesh = plan_mesh(spec, TOPOLOGY)
                prefix = spec.subnet.rsplit(".", 1)[0]
                for member in mesh.members:
                    self.assertTrue(member.address.startswith(prefix + "."))

    def test_no_two_members_share_an_address(self):
        mesh = plan_mesh(SWARM, TOPOLOGY)
        addresses = [m.address for m in mesh.members]
        self.assertEqual(len(addresses), len(set(addresses)))

    def test_the_two_meshes_do_not_share_an_address(self):
        swarm = {m.address for m in plan_mesh(SWARM, TOPOLOGY).members}
        data = {m.address for m in plan_mesh(DATA, TOPOLOGY).members}
        self.assertEqual(swarm & data, set())


class TestAddressPersistence(unittest.TestCase):
    def _held(self, spec, topology) -> dict[str, str]:
        return {m.host: m.address for m in plan_mesh(spec, topology).members}

    def test_a_member_that_sorts_first_does_not_renumber_the_others(self):
        before = self._held(SWARM, TOPOLOGY)
        grown = _with_spokes(swarm=("alpha-wrk-00", *TOPOLOGY.spokes["swarm"]))

        mesh = plan_mesh(SWARM, grown, addresses=before)
        after = {m.host: m.address for m in mesh.members}
        for host, address in before.items():
            with self.subTest(host=host):
                self.assertEqual(after[host], address)
        self.assertNotIn(after["alpha-wrk-00"], set(before.values()))

    def test_rotation_replaces_identities_and_keeps_addresses(self):
        before = self._held(SWARM, TOPOLOGY)
        mesh = plan_mesh(SWARM, TOPOLOGY, rotate=True, addresses=before)
        self.assertEqual({m.host: m.address for m in mesh.members}, before)

    def test_a_stored_address_outside_the_subnet_is_replaced(self):
        mesh = plan_mesh(SWARM, TOPOLOGY, addresses={"swarm-wrk-01": "10.99.0.50"})
        address = mesh.member("swarm-wrk-01").address
        self.assertTrue(address.startswith("10.100.0."))

    def test_a_spoke_never_adopts_the_hub_address(self):
        hub = plan_mesh(SWARM, TOPOLOGY).hub.address
        mesh = plan_mesh(SWARM, TOPOLOGY, addresses={"swarm-wrk-01": hub})
        self.assertNotEqual(mesh.member("swarm-wrk-01").address, hub)

    def test_a_hand_pinned_address_below_the_allocation_start_is_kept(self):
        mesh = plan_mesh(SWARM, TOPOLOGY, addresses={"swarm-wrk-01": "10.100.0.2"})
        self.assertEqual("10.100.0.2", mesh.member("swarm-wrk-01").address)

    def test_a_stored_broadcast_address_is_replaced(self):
        mesh = plan_mesh(SWARM, TOPOLOGY, addresses={"swarm-wrk-01": "10.100.0.255"})
        self.assertNotEqual("10.100.0.255", mesh.member("swarm-wrk-01").address)

    def test_two_members_claiming_one_address_do_not_both_keep_it(self):
        taken = plan_mesh(SWARM, TOPOLOGY).member("swarm-wrk-01").address
        mesh = plan_mesh(
            SWARM,
            TOPOLOGY,
            addresses={"swarm-wrk-01": taken, "swarm-wrk-02": taken},
        )
        addresses = [m.address for m in mesh.members]
        self.assertEqual(len(addresses), len(set(addresses)))


class TestPeering(unittest.TestCase):
    def test_the_hub_peers_with_every_spoke(self):
        mesh = plan_mesh(SWARM, TOPOLOGY)
        self.assertEqual(
            {p.host for p in mesh.peers_of(mesh.hub.host)},
            {s.host for s in mesh.spokes},
        )

    def test_a_spoke_peers_only_with_the_hub(self):
        mesh = plan_mesh(SWARM, TOPOLOGY)
        for spoke in mesh.spokes:
            with self.subTest(spoke=spoke.host):
                peers = mesh.peers_of(spoke.host)
                self.assertEqual([p.host for p in peers], [mesh.hub.host])

    def test_a_host_outside_the_mesh_has_no_peers(self):
        mesh = plan_mesh(SWARM, TOPOLOGY)
        self.assertEqual(mesh.peers_of("nfs-server"), ())


class TestRoaming(unittest.TestCase):
    ROAMING = Topology(
        hub=TOPOLOGY.hub,
        spokes=TOPOLOGY.spokes,
        roaming=frozenset({"swarm-wrk-02"}),
    )

    def test_a_roaming_spoke_has_no_endpoint(self):
        member = plan_mesh(SWARM, self.ROAMING).member("swarm-wrk-02")
        self.assertTrue(member.roaming)
        self.assertEqual("", member.endpoint)

    def test_a_spoke_without_the_mark_keeps_its_endpoint(self):
        member = plan_mesh(SWARM, self.ROAMING).member("swarm-wrk-01")
        self.assertFalse(member.roaming)
        self.assertEqual("swarm-wrk-01", member.endpoint)

    def test_a_roaming_spoke_still_peers_with_the_hub_alone(self):
        mesh = plan_mesh(SWARM, self.ROAMING)
        self.assertEqual(
            [TOPOLOGY.hub], [peer.host for peer in mesh.peers_of("swarm-wrk-02")]
        )

    def test_the_hub_still_peers_with_a_roaming_spoke(self):
        mesh = plan_mesh(SWARM, self.ROAMING)
        self.assertIn("swarm-wrk-02", [p.host for p in mesh.peers_of(TOPOLOGY.hub)])

    def test_an_endpoint_for_a_roaming_spoke_is_refused(self):
        with self.assertRaises(ValueError) as raised:
            plan_mesh(SWARM, self.ROAMING, endpoints={"swarm-wrk-02": "192.0.2.4"})
        self.assertIn("swarm-wrk-02", str(raised.exception))

    def test_a_topology_without_roamers_marks_nobody(self):
        mesh = plan_mesh(SWARM, TOPOLOGY)
        self.assertFalse(any(member.roaming for member in mesh.members))
        self.assertTrue(all(member.endpoint for member in mesh.members))


class TestPrimaryMesh(unittest.TestCase):
    def test_the_first_declared_mesh_a_host_belongs_to_is_its_primary(self):
        self.assertEqual(
            primary_meshes([SWARM, DATA], TOPOLOGY),
            {
                "swarm-mgr-01": "swarm",
                "swarm-wrk-01": "swarm",
                "swarm-wrk-02": "swarm",
                "nfs-server": "data",
                "swarm-bkp-01": "data",
            },
        )

    def test_reordering_the_declarations_moves_the_hubs_primary(self):
        self.assertEqual(
            primary_meshes([DATA, SWARM], TOPOLOGY)["swarm-mgr-01"], "data"
        )

    def test_a_spoke_of_two_meshes_keeps_the_first(self):
        topology = _with_spokes(beta=("nfs-server",))
        beta = MeshSpec(name="beta", subnet="10.100.11.0/24", listen_port=51831)
        self.assertEqual(primary_meshes([beta, DATA], topology)["nfs-server"], "beta")

    def test_the_controller_counts_only_where_it_joins(self):
        primary = primary_meshes(
            [SWARM, DATA], TOPOLOGY, controller="localhost", controller_mesh="data"
        )
        self.assertEqual(primary["localhost"], "data")
        self.assertNotIn("localhost", primary_meshes([SWARM, DATA], TOPOLOGY))


class TestKeyPairing(unittest.TestCase):
    def test_every_public_key_answers_for_its_private_key(self):
        mesh = plan_mesh(SWARM, TOPOLOGY)
        for member in mesh.members:
            with self.subTest(host=member.host):
                self.assertIsNotNone(member.private_key)
                self.assertEqual(public_key_of(member.private_key), member.public_key)

    def test_no_two_members_share_a_keypair(self):
        mesh = plan_mesh(SWARM, TOPOLOGY)
        self.assertEqual(len({m.private_key for m in mesh.members}), len(mesh.members))

    def test_a_peer_entry_never_carries_a_private_key(self):
        mesh = plan_mesh(SWARM, TOPOLOGY)
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
        held = {"swarm-wrk-01": public_key_of(generate_private_key())}
        mesh = plan_mesh(SWARM, TOPOLOGY, held)
        member = mesh.member("swarm-wrk-01")
        self.assertEqual(member.public_key, held["swarm-wrk-01"])
        self.assertIsNone(member.private_key)

    def test_a_new_member_is_keyed_while_the_others_are_untouched(self):
        held = {
            host: public_key_of(generate_private_key())
            for host in ("swarm-mgr-01", "swarm-wrk-01")
        }
        mesh = plan_mesh(SWARM, TOPOLOGY, held)
        self.assertIsNone(mesh.member("swarm-wrk-01").private_key)
        self.assertIsNotNone(mesh.member("swarm-wrk-02").private_key)

    def test_rotation_replaces_every_key_including_held_ones(self):
        held = {
            host: public_key_of(generate_private_key())
            for host in ("swarm-mgr-01", "swarm-wrk-01", "swarm-wrk-02")
        }
        mesh = plan_mesh(SWARM, TOPOLOGY, held, rotate=True)
        for member in mesh.members:
            with self.subTest(host=member.host):
                self.assertIsNotNone(member.private_key)
                self.assertNotEqual(member.public_key, held[member.host])

    def test_rotation_keeps_the_mesh_internally_consistent(self):
        mesh = plan_mesh(SWARM, TOPOLOGY, rotate=True)
        published = {m.host: m.public_key for m in mesh.members}
        for member in mesh.members:
            for peer in mesh.peers_of(member.host):
                with self.subTest(host=member.host, peer=peer.host):
                    self.assertEqual(peer.public_key, published[peer.host])


class TestSubnetGuards(unittest.TestCase):
    def test_overlapping_meshes_are_refused(self):
        clash = MeshSpec(name="clash", subnet="10.100.0.0/25", listen_port=51822)
        with self.assertRaises(ValueError):
            assert_no_subnet_overlap([SWARM, clash], "10.100.0.0/16")

    def test_a_subnet_outside_the_pool_is_refused(self):
        escapee = MeshSpec(name="escapee", subnet="192.168.244.0/24", listen_port=51823)
        with self.assertRaises(ValueError):
            assert_no_subnet_overlap([escapee], "10.100.0.0/16")

    def test_a_shared_listen_port_is_refused(self):
        twin = MeshSpec(
            name="twin", subnet="10.100.9.0/24", listen_port=SWARM.listen_port
        )
        with self.assertRaises(ValueError):
            assert_no_subnet_overlap([SWARM, twin], "10.100.0.0/16")

    def test_the_declared_meshes_pass_their_own_guards(self):
        assert_no_subnet_overlap([SWARM, DATA], "10.100.0.0/16")


MESH_POOL = "10.100.0.0/16"


def topology(mesh_count: int, seed: int) -> tuple[list[MeshSpec], Topology]:
    """A hub-and-spoke topology of ``mesh_count`` meshes around one hub.

    Args:
        mesh_count: how many meshes to declare.
        seed: picks one arrangement of hosts over the meshes.
    """
    hosts = [f"node-{index:02d}" for index in range(12)]
    spokes: dict[str, tuple[str, ...]] = {}
    specs: list[MeshSpec] = []
    for index in range(mesh_count):
        name = f"mesh-{index}"
        spokes[name] = tuple(
            host
            for position, host in enumerate(hosts)
            if (position + seed) % (index + 2)
        )
        specs.append(
            MeshSpec(
                name=name, subnet=f"10.100.{index}.0/24", listen_port=51820 + index
            )
        )
    return specs, Topology(hub="hub-01", spokes=spokes)


class TestAnyNumberOfMeshes(unittest.TestCase):
    COUNTS = range(1, 9)
    SEEDS = range(3)

    def _planned(self, count: int, seed: int):
        specs, layout = topology(count, seed)
        return specs, layout, [plan_mesh(spec, layout) for spec in specs]

    def test_every_declared_count_plans_without_collision(self):
        for count in self.COUNTS:
            for seed in self.SEEDS:
                with self.subTest(meshes=count, seed=seed):
                    specs, _, meshes = self._planned(count, seed)
                    assert_no_subnet_overlap(specs, MESH_POOL)
                    self.assertEqual(len(meshes), count)

    def test_every_member_is_addressed_inside_its_own_subnet(self):
        for count in self.COUNTS:
            for seed in self.SEEDS:
                specs, _, meshes = self._planned(count, seed)
                for spec, mesh in zip(specs, meshes, strict=True):
                    prefix = spec.subnet.rsplit(".", 1)[0] + "."
                    for member in mesh.members:
                        with self.subTest(meshes=count, seed=seed, host=member.host):
                            self.assertTrue(member.address.startswith(prefix))

    def test_no_two_members_of_one_mesh_share_an_address(self):
        for count in self.COUNTS:
            for seed in self.SEEDS:
                _, _, meshes = self._planned(count, seed)
                for mesh in meshes:
                    with self.subTest(meshes=count, seed=seed, mesh=mesh.spec.name):
                        addresses = [member.address for member in mesh.members]
                        self.assertEqual(len(addresses), len(set(addresses)))

    def test_the_hub_joins_every_mesh_so_the_planes_can_reach_each_other(self):
        for count in self.COUNTS:
            for seed in self.SEEDS:
                _, _, meshes = self._planned(count, seed)
                for mesh in meshes:
                    with self.subTest(meshes=count, seed=seed, mesh=mesh.spec.name):
                        self.assertEqual("hub-01", mesh.hub.host)

    def test_the_hub_peers_with_every_spoke_and_a_spoke_only_with_the_hub(self):
        for count in self.COUNTS:
            for seed in self.SEEDS:
                _, _, meshes = self._planned(count, seed)
                for mesh in meshes:
                    with self.subTest(meshes=count, seed=seed, mesh=mesh.spec.name):
                        self.assertEqual(
                            sorted(peer.host for peer in mesh.peers_of(mesh.hub.host)),
                            sorted(spoke.host for spoke in mesh.spokes),
                        )
                        for spoke in mesh.spokes:
                            self.assertEqual(
                                ["hub-01"],
                                [peer.host for peer in mesh.peers_of(spoke.host)],
                            )

    def test_a_host_in_several_meshes_holds_one_address_per_mesh(self):
        shared = 0
        for count in self.COUNTS:
            for seed in self.SEEDS:
                _, _, meshes = self._planned(count, seed)
                held: dict[str, set[str]] = {}
                for mesh in meshes:
                    for member in mesh.members:
                        held.setdefault(member.host, set()).add(member.address)
                for host, addresses in held.items():
                    count_in = sum(
                        1
                        for mesh in meshes
                        if any(m.host == host for m in mesh.members)
                    )
                    if count_in > 1:
                        shared += 1
                        with self.subTest(meshes=count, seed=seed, host=host):
                            self.assertEqual(count_in, len(addresses))
        self.assertGreater(shared, 0, "no host landed in several meshes")

    def test_every_peer_entry_carries_a_usable_public_key(self):
        for count in self.COUNTS:
            _, _, meshes = self._planned(count, 0)
            for mesh in meshes:
                for member in mesh.members:
                    for peer in mesh.peers_of(member.host):
                        with self.subTest(meshes=count, host=member.host):
                            self.assertTrue(is_valid_public_key(peer.public_key))
