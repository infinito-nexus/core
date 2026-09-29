import unittest

from plugins.lookup.node_hosts import SWARM_GROUP, LookupModule, node_hosts

LOCAL = "localhost"
NODES = ["swarm-mgr-01", "swarm-wrk-01", "swarm-wrk-02"]


class TestNodeHosts(unittest.TestCase):
    def test_every_swarm_node_is_returned(self) -> None:
        self.assertEqual(
            node_hosts({"groups": {SWARM_GROUP: NODES}, "inventory_hostname": LOCAL}),
            NODES,
        )

    def test_without_the_group_the_local_host_stands_alone(self) -> None:
        self.assertEqual(
            node_hosts({"groups": {}, "inventory_hostname": LOCAL}), [LOCAL]
        )

    def test_an_empty_group_falls_back_to_the_local_host(self) -> None:
        """An empty group would otherwise create the path on no host at all."""
        self.assertEqual(
            node_hosts({"groups": {SWARM_GROUP: []}, "inventory_hostname": LOCAL}),
            [LOCAL],
        )

    def test_absent_groups_are_not_an_error(self) -> None:
        self.assertEqual(node_hosts({"inventory_hostname": LOCAL}), [LOCAL])

    def test_the_lookup_reads_the_variables_it_is_handed(self) -> None:
        lookup = LookupModule()
        lookup._templar = None
        self.assertEqual(
            lookup.run(
                [], {"groups": {SWARM_GROUP: NODES}, "inventory_hostname": LOCAL}
            ),
            NODES,
        )


if __name__ == "__main__":
    unittest.main()
