from __future__ import annotations

import unittest
from unittest import mock

from utils.tests.swarm import matrix


class TestSwarmDeployCommands(unittest.TestCase):
    @mock.patch.object(matrix, "run_step", return_value=0)
    def test_round_deploy_keeps_the_placed_custom_roles(self, run_step):
        matrix._deploy(
            app_id="web-app-cst-demo",
            inv_dir="/tmp/inv-0",
            extras_path="/tmp/extras.yml",
            round_index=0,
            total=1,
        )
        cmd = run_step.call_args.kwargs["cmd"]
        self.assertIn("cli.administration.deploy.swarm", cmd)
        self.assertIn("--skip-pull", cmd)

    @mock.patch.object(matrix, "run_step", return_value=0)
    def test_backup_host_deploy_keeps_the_placed_custom_roles(self, run_step):
        matrix._deploy_backup_host(
            app_id="web-app-cst-demo",
            inv_dir="/tmp/inv-0",
            extras_path="/tmp/extras.yml",
        )
        cmd = run_step.call_args.kwargs["cmd"]
        self.assertIn("cli.administration.deploy.dedicated", cmd)
        self.assertIn("--skip-pull", cmd)


if __name__ == "__main__":
    unittest.main()
