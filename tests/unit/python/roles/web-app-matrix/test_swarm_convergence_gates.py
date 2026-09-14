from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

SERVICES = (
    PROJECT_ROOT / "roles/web-app-matrix/templates/flavor/compose/services.yml.j2"
)


class TestSwarmConvergenceGates(unittest.TestCase):
    def test_bridge_health_does_not_wait_for_the_homeserver_ping(self) -> None:
        probes = re.findall(r"/_matrix/mau/(\w+)", read_text(str(SERVICES)))
        self.assertTrue(probes)
        self.assertEqual(
            set(probes),
            {"live"},
            "a /ready probe waits for Synapse to reach the bridge, which swarm "
            "only allows once the task is healthy",
        )

    def test_chatgpt_bot_waits_for_the_token_provisioning_issues(self) -> None:
        guard = next(
            line
            for line in read_text(str(SERVICES)).splitlines()
            if "plugins.chatgpt" in line and line.lstrip().startswith("{% if")
        )
        self.assertIn(
            "MATRIX_CHATGPT_ACCESS_TOKEN",
            guard,
            "the bot account and its token only exist after stack_host_provisioning, "
            "so an earlier bot task fails its login until swarm's converge wait "
            "calls it stuck",
        )


if __name__ == "__main__":
    unittest.main()
