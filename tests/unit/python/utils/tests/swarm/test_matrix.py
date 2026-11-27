from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
import unittest.mock

from cli.administration.deploy.development.deploy import run as deploy_run
from utils.tests.swarm import deploy as swarm_deploy
from utils.tests.swarm import matrix as swarm_matrix

DEPLOY_IMAGE_TAG = "cli.administration.deploy.development.deploy.run.deploy_image_tag"
TOPOLOGY = {
    "SWARM_LAB_NETWORK": "web-app-docs-swarm-lab",
    "MGR": "web-app-docs-swarm-mgr-01",
    "WRK1": "web-app-docs-swarm-wrk-01",
    "WRK2": "web-app-docs-swarm-wrk-02",
}


class TestSharedTargetReset(unittest.TestCase):
    @unittest.mock.patch.dict(os.environ, TOPOLOGY)
    @unittest.mock.patch.object(swarm_deploy, "run_step", return_value=0)
    def test_the_lab_and_every_swarm_node_go_to_the_shared_reset(self, run):
        self.assertEqual(swarm_deploy.reset_target(), 0)
        self.assertEqual(
            run.call_args.args[0],
            [
                "python3",
                "-m",
                "cli.administration.deploy.development",
                "target-reset",
                "--lab",
                TOPOLOGY["SWARM_LAB_NETWORK"],
                "--node",
                TOPOLOGY["MGR"],
                "--node",
                TOPOLOGY["WRK1"],
                "--node",
                TOPOLOGY["WRK2"],
            ],
        )


class TestSwarmDeployCommands(unittest.TestCase):
    @unittest.mock.patch.dict(
        os.environ,
        {**TOPOLOGY, "INFINITO_IMAGE": "ghcr.io/infinito-nexus/core/arch:ci-0"},
    )
    @unittest.mock.patch(DEPLOY_IMAGE_TAG, return_value="ci-0")
    @unittest.mock.patch.object(swarm_deploy, "run_step", return_value=0)
    def test_every_pass_of_a_round_starts_on_a_reset_target(self, run, _tag):
        for update_pass in (False, True):
            run.reset_mock()
            swarm_deploy.deploy_round(
                app_id="web-app-semaphore",
                inv_dir="/tmp/inv-0",
                extras_path="/tmp/extras.yml",
                round_index=0,
                total=1,
                update_pass=update_pass,
            )
            first, second = run.call_args_list
            self.assertIn("target-reset", first.args[0])
            self.assertIn("cli.administration.deploy.swarm", second.kwargs["cmd"])

    @unittest.mock.patch.dict(os.environ, TOPOLOGY)
    @unittest.mock.patch.object(swarm_deploy, "run_step", return_value=3)
    def test_a_failed_reset_deploys_nothing(self, run):
        rc = swarm_deploy.deploy_round(
            app_id="web-app-semaphore",
            inv_dir="/tmp/inv-0",
            extras_path="/tmp/extras.yml",
            round_index=0,
            total=1,
        )
        self.assertEqual(rc, 3)
        self.assertEqual(run.call_count, 1)

    @unittest.mock.patch.dict(
        os.environ,
        {**TOPOLOGY, "INFINITO_IMAGE": "ghcr.io/infinito-nexus/core/arch:ci-0"},
    )
    @unittest.mock.patch(DEPLOY_IMAGE_TAG, return_value="ci-0")
    @unittest.mock.patch.object(swarm_deploy, "run_step", return_value=0)
    def test_round_deploy_keeps_the_placed_custom_roles(self, run, _tag):
        swarm_deploy.deploy_round(
            app_id="web-app-cst-demo",
            inv_dir="/tmp/inv-0",
            extras_path="/tmp/extras.yml",
            round_index=0,
            total=1,
        )
        cmd = run.call_args.kwargs["cmd"]
        self.assertIn("cli.administration.deploy.swarm", cmd)
        self.assertIn("--skip-pull", cmd)

    @unittest.mock.patch.object(swarm_deploy, "run_step", return_value=0)
    def test_backup_host_deploy_keeps_the_placed_custom_roles(self, run):
        with tempfile.TemporaryDirectory() as inv_dir:
            swarm_deploy.deploy_backup_host(
                app_id="web-app-cst-demo",
                inv_dir=inv_dir,
                extras_path="/tmp/extras.yml",
            )
        cmd = run.call_args.kwargs["cmd"]
        self.assertIn("cli.administration.deploy.dedicated", cmd)
        self.assertIn("--skip-pull", cmd)


class TestSwarmDeployImage(unittest.TestCase):
    def deploy_env(self, run):
        swarm_deploy.deploy_round(
            app_id="web-app-semaphore",
            inv_dir="/tmp/inv-0",
            extras_path="/tmp/extras.yml",
            round_index=0,
            total=1,
        )
        return run.call_args.kwargs["env"]

    @unittest.mock.patch.dict(
        os.environ,
        {
            **TOPOLOGY,
            "INFINITO_IMAGE": "ghcr.io/infinito-nexus/core/arch:ci-0",
            "INFINITO_IMAGE_TAG": "latest",
        },
    )
    @unittest.mock.patch(DEPLOY_IMAGE_TAG, return_value="ci-0")
    @unittest.mock.patch.object(swarm_deploy, "run_step", return_value=0)
    def test_the_round_deploys_with_the_tag_of_this_checkout(self, run, _tag):
        env = self.deploy_env(run)
        self.assertEqual(env["INFINITO_IMAGE_TAG"], "ci-0")
        self.assertEqual(env["INFINITO_IMAGE"], "ghcr.io/infinito-nexus/core/arch:ci-0")

    @unittest.mock.patch.dict(os.environ, {**TOPOLOGY, "INFINITO_IMAGE": ""})
    @unittest.mock.patch.object(
        deploy_run.subprocess,
        "run",
        return_value=subprocess.CompletedProcess([], 0, stdout="core/arch\n"),
    )
    @unittest.mock.patch(DEPLOY_IMAGE_TAG, return_value="dev-0")
    @unittest.mock.patch.object(swarm_deploy, "run_step", return_value=0)
    def test_an_unresolved_image_becomes_the_local_image_name(self, run, _tag, resolve):
        env = self.deploy_env(run)
        self.assertEqual(env["INFINITO_IMAGE"], "core/arch")
        self.assertEqual(env["INFINITO_IMAGE_TAG"], "dev-0")
        self.assertEqual(
            resolve.call_args.args[0][-1], str(deploy_run._LOCAL_IMAGE_SCRIPT)
        )


class TestSwarmProvisionPayload(unittest.TestCase):
    @unittest.mock.patch.object(swarm_matrix, "_run", return_value=0)
    def test_the_vars_payload_keeps_its_declared_key_order(self, run):
        canonical = {"web": "multi.example", "provider": "provider.multi.example"}
        swarm_matrix._provision(
            app_id="web-app-multi",
            inv_dir="/inv",
            round_variants={"web-app-multi": 1},
            vars_payload={
                "applications": {"web-app-multi": {"domains": {"canonical": canonical}}}
            },
        )
        payload = json.loads(run.call_args.kwargs["env"]["INFINITO_VARS_PAYLOAD"])
        self.assertEqual(
            list(payload["applications"]["web-app-multi"]["domains"]["canonical"]),
            ["web", "provider"],
        )


if __name__ == "__main__":
    unittest.main()
