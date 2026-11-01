from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ansible.parsing.splitter import parse_kv

from cli.administration.deploy.development.deploy.run import _run_deploy


class TestRunDeploy(unittest.TestCase):
    def deploy_cmd(self, extra_ansible_vars=None) -> list[str]:
        compose = mock.Mock()
        compose.exec.return_value = SimpleNamespace(returncode=0)
        _run_deploy(
            compose,
            deploy_ids=["web-app-cst-demo"],
            debug=False,
            passthrough=[],
            inventory_dir="/etc/inventories/dev",
            container_name="infinito",
            extra_ansible_vars=extra_ansible_vars,
        )
        return compose.exec.call_args.args[0]

    def test_a_list_extra_var_survives_ansible_key_value_parsing(self):
        apps = ["web-app-gitea", "web-app-lam"]
        cmd = self.deploy_cmd({"PRIMARY_APPS": apps, "VARIANT_INDEX": 0})
        extra_vars = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-e"]
        parsed = {}
        for extra_var in extra_vars:
            parsed.update(parse_kv(extra_var))
        self.assertNotIn("_raw_params", parsed)
        self.assertEqual(apps, json.loads(parsed["PRIMARY_APPS"]))
        self.assertEqual(0, json.loads(parsed["VARIANT_INDEX"]))

    def test_deploys_the_generated_inventory(self):
        cmd = self.deploy_cmd()
        self.assertEqual("/etc/inventories/dev/devices.yml", cmd[3])
        self.assertEqual(["--id", "web-app-cst-demo"], cmd[-2:])

    def test_generated_inventory_keeps_the_placed_custom_roles(self):
        self.assertIn("--skip-pull", self.deploy_cmd())


if __name__ == "__main__":
    unittest.main()
