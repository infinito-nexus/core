from __future__ import annotations

import unittest

from utils.agents import budget

GIB = 1024**3
RUNTIMES = {"hermes": 4 * GIB, "openclaw": 6 * GIB, "claude-code": 2 * GIB}
SMALL = {"vcpu": 2, "memory": 4 * GIB, "disk": 32 * GIB}
LARGE = {"vcpu": 8, "memory": 16 * GIB, "disk": 64 * GIB}


class TestAgentsReservation(unittest.TestCase):
    def test_uses_the_largest_reservation(self):
        self.assertEqual(budget.agents_reservation(3, RUNTIMES, 0), 18 * GIB)

    def test_counts_the_warm_pool_next_to_max_running(self):
        self.assertEqual(budget.agents_reservation(3, RUNTIMES, 2), 30 * GIB)

    def test_nothing_runs_nothing_reserved(self):
        self.assertEqual(budget.agents_reservation(0, RUNTIMES, 0), 0)
        self.assertEqual(budget.agents_reservation(2, {}, 1), 0)

    def test_fits(self):
        self.assertTrue(budget.fits(3, RUNTIMES, 10 * GIB, 32 * GIB, 0))
        self.assertFalse(budget.fits(3, RUNTIMES, 20 * GIB, 32 * GIB, 0))
        self.assertFalse(budget.fits(3, RUNTIMES, 10 * GIB, 32 * GIB, 1))


class TestVmHost(unittest.TestCase):
    def test_demand_is_count_times_largest_size(self):
        self.assertEqual(
            budget.vm_demand(2, 1, [SMALL, LARGE]),
            {"vcpu": 24, "memory": 48 * GIB, "disk": 192 * GIB},
        )

    def test_no_vm_agents_demand_nothing(self):
        self.assertEqual(
            budget.vm_demand(5, 2, []), {"vcpu": 0, "memory": 0, "disk": 0}
        )

    def test_host_below_demand_plus_reserve_is_refused(self):
        demand = budget.vm_demand(1, 1, [SMALL])
        reserve = {"memory": 2 * GIB, "disk": 10 * GIB}
        enough = {"memory": 10 * GIB, "disk": 74 * GIB}
        self.assertEqual(budget.vm_host_shortages(demand, enough, reserve), [])
        short = {"memory": 9 * GIB, "disk": 73 * GIB}
        found = budget.vm_host_shortages(demand, short, reserve)
        self.assertEqual(len(found), 2)
        self.assertTrue(found[0].startswith("free memory"))
        self.assertTrue(found[1].startswith("free disk"))

    def test_container_limits_cover_demand_plus_overhead(self):
        demand = budget.vm_demand(1, 1, [SMALL])
        required = budget.container_limits(demand, {"cpus": 1, "memory": 2 * GIB})
        self.assertEqual(required, {"cpus": 5.0, "memory": 10 * GIB})
        self.assertEqual(budget.container_limit_shortages(required, 5, 10 * GIB), [])
        found = budget.container_limit_shortages(required, 4.5, 8 * GIB)
        self.assertEqual(len(found), 2)


if __name__ == "__main__":
    unittest.main()
