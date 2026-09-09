import unittest

from plugins.lookup.playwright_workers import LookupModule, compute_workers


class TestComputeWorkers(unittest.TestCase):
    def test_local_20c_64g(self):
        self.assertEqual(compute_workers(20, 64.0, False), 5)

    def test_local_12c_31g(self):
        self.assertEqual(compute_workers(12, 31.0, False), 3)

    def test_hard_cap_binds(self):
        self.assertEqual(compute_workers(64, 256.0, False), 6)

    def test_ram_binds(self):
        self.assertEqual(compute_workers(20, 3.0, False), 1)

    def test_ci_cap_binds(self):
        self.assertEqual(compute_workers(16, 64.0, True), 2)

    def test_ci_small_runner(self):
        self.assertEqual(compute_workers(2, 8.0, True), 1)

    def test_floor_is_one(self):
        self.assertEqual(compute_workers(1, 1.0, False), 1)

    def test_kwargs_override(self):
        self.assertEqual(
            compute_workers(20, 64.0, False, cpu_divisor=2, hard_cap=100), 10
        )

    def test_onion_lifts_the_ci_runner_off_one_worker(self):
        """The CI ceiling describes CPU contention, which Tor does not create.

        The 4-core runner yields one worker because a quarter of four cores is
        one. Over Tor the phase waits on circuits instead, so the count is
        raised rather than derived from cores.
        """
        self.assertEqual(compute_workers(4, 16.0, True), 1)
        self.assertEqual(compute_workers(4, 16.0, True, onion=True), 2)

    def test_onion_still_respects_memory(self):
        """Circuits are cheap, browsers are not: RAM keeps its veto."""
        self.assertEqual(compute_workers(20, 3.0, False, onion=True), 1)

    def test_onion_cap_binds_on_a_large_host(self):
        self.assertEqual(compute_workers(64, 256.0, False, onion=True), 4)


class TestLookup(unittest.TestCase):
    def test_returns_single_int_ge_1(self):
        out = LookupModule().run([], variables={})
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], int)
        self.assertGreaterEqual(out[0], 1)


if __name__ == "__main__":
    unittest.main()
