from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from cli.administration.deploy.development.deploy.run import _run_deploy


class TestRunDeploy(unittest.TestCase):
    def deploy_cmd(self) -> list[str]:
        compose = mock.Mock()
        compose.exec.return_value = SimpleNamespace(returncode=0)
        _run_deploy(
            compose,
            deploy_ids=["web-app-cst-demo"],
            debug=False,
            passthrough=[],
            inventory_dir="/etc/inventories/dev",
            container_name="infinito",
        )
        return compose.exec.call_args.args[0]

    def test_deploys_the_generated_inventory(self):
        cmd = self.deploy_cmd()
        self.assertEqual("/etc/inventories/dev/devices.yml", cmd[3])
        self.assertEqual(["--id", "web-app-cst-demo"], cmd[-2:])

    def test_generated_inventory_keeps_the_placed_custom_roles(self):
        self.assertIn("--skip-pull", self.deploy_cmd())


if __name__ == "__main__":
    unittest.main()
