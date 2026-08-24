from __future__ import annotations

import unittest

from cli.administration.deploy.ci import runs
from tests.utils.ci.job_names import deploy_job_name, orchestrator_prefix

MODES = ("docker", "swarm", "host")
SAMPLE_APP = "web-app-matomo"
SAMPLE_VARIANTS = ("", "0", "2")


class TestCiDeployJobNamesParse(unittest.TestCase):
    def test_parser_matches_rendered_workflow_names(self) -> None:
        for mode in MODES:
            for variant in SAMPLE_VARIANTS:
                for orchestrated in (False, True):
                    name = deploy_job_name(
                        mode, SAMPLE_APP, variant, orchestrated=orchestrated
                    )
                    statuses = runs.parse_role_statuses(
                        [{"name": name, "status": "completed", "conclusion": "failure"}]
                    )
                    self.assertIn(
                        SAMPLE_APP, statuses, f"parser missed app in {name!r}"
                    )
                    self.assertEqual(
                        {mode}, set(statuses[SAMPLE_APP]), f"wrong mode for {name!r}"
                    )

    def test_failed_roles_detect_each_scope(self) -> None:
        jobs = [
            {
                "name": deploy_job_name(mode, SAMPLE_APP, "1"),
                "status": "completed",
                "conclusion": "failure",
            }
            for mode in MODES
        ]
        statuses = runs.parse_role_statuses(jobs)
        self.assertEqual(runs.failed_roles(statuses, "swarm"), [SAMPLE_APP])
        self.assertEqual(runs.failed_roles(statuses, "docker"), [SAMPLE_APP])
        self.assertEqual(runs.failed_roles(statuses, "total"), [SAMPLE_APP])

    def test_non_deploy_jobs_are_ignored(self) -> None:
        noise = [
            {"name": orchestrator_prefix(0) + "⛵ Navigate composition"},
            {"name": orchestrator_prefix(1) + "🍯 Lure swarm"},
            {"name": "🐳 Update Docker image versions"},
        ]
        self.assertEqual(runs.parse_role_statuses(noise), {})


if __name__ == "__main__":
    unittest.main()
