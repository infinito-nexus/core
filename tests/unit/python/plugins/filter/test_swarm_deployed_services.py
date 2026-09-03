"""Only the service lines of a stack deploy may reach the convergence gate."""

from __future__ import annotations

import unittest

from plugins.filter.swarm.deployed_services import swarm_deployed_services


class TestSwarmDeployedServices(unittest.TestCase):
    def test_it_keeps_created_and_updated_services_in_order(self) -> None:
        result = {
            "stdout_lines": [
                "2026-09-03T01:24:03Z",
                "Creating network cdn_default",
                "Creating service cdn_build",
                "Updating service cdn_web (id: 9x)",
            ]
        }
        self.assertEqual(swarm_deployed_services(result), ["cdn_build", "cdn_web"])

    def test_it_drops_every_non_service_line(self) -> None:
        result = {
            "stdout_lines": [
                "2026-09-03T01:24:03Z",
                "Creating config cdn_nginx",
                "Creating secret cdn_key",
                "Updating network cdn_default",
            ]
        }
        self.assertEqual(swarm_deployed_services(result), [])

    def test_a_service_name_never_carries_the_trailing_id(self) -> None:
        result = {"stdout_lines": ["Updating service demo_web (id: abc123)"]}
        self.assertEqual(swarm_deployed_services(result), ["demo_web"])

    def test_a_missing_or_empty_result_yields_nothing(self) -> None:
        self.assertEqual(swarm_deployed_services(None), [])
        self.assertEqual(swarm_deployed_services({}), [])
        self.assertEqual(swarm_deployed_services({"stdout_lines": None}), [])


if __name__ == "__main__":
    unittest.main()
