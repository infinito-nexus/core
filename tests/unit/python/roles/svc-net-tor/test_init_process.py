from __future__ import annotations

import unittest

from .test_rolling_update import render


class TestInitProcess(unittest.TestCase):
    def test_tor_runs_under_an_init_in_both_modes(self) -> None:
        for swarm in (True, False):
            with self.subTest(swarm=swarm):
                self.assertIn("    init: true", render(swarm).splitlines())


if __name__ == "__main__":
    unittest.main()
