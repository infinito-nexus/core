from __future__ import annotations

import unittest

from cli.administration.deploy.ci import runs
from tests.utils.ci_job_names import ORCHESTRATOR_PREFIX, deploy_job_name

MODES = ("docker", "swarm")
SAMPLE_APP = "web-app-matomo"
SAMPLE_VARIANTS = ("", "0", "0,1", "0,1,2")


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
                "name": deploy_job_name(mode, SAMPLE_APP, "0,1"),
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
            {"name": ORCHESTRATOR_PREFIX["docker"] + "⛵ Navigate composition"},
            {"name": ORCHESTRATOR_PREFIX["swarm"] + "🍯 Lure swarm"},
            {"name": "🐳 Update Docker image versions"},
        ]
        self.assertEqual(runs.parse_role_statuses(noise), {})


if __name__ == "__main__":
    unittest.main()
