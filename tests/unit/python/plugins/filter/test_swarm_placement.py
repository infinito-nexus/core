import unittest

from plugins.filter.swarm.placement import swarm_placement_constraints

LABEL = "infinito.stack_host"


class TestSwarmPlacementConstraints(unittest.TestCase):
    def test_no_placement_has_no_constraint(self):
        self.assertEqual(swarm_placement_constraints("", ["m1", "m2"], LABEL), [])

    def test_a_single_manager_needs_no_stack_host_pin(self):
        self.assertEqual(
            swarm_placement_constraints("manager", ["m1"], LABEL),
            ["node.role == manager"],
        )

    def test_several_managers_pin_to_the_stack_host(self):
        self.assertEqual(
            swarm_placement_constraints("manager", ["m1", "m2", "m3"], LABEL),
            ["node.role == manager", f"node.labels.{LABEL} == true"],
        )

    def test_a_worker_placement_never_carries_the_stack_host_pin(self):
        self.assertEqual(
            swarm_placement_constraints("worker", ["m1", "m2"], LABEL),
            ["node.role == worker"],
        )


if __name__ == "__main__":
    unittest.main()
