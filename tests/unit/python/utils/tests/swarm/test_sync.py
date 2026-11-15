"""The swarm role sync resolves the round inventory the matrix wrote and runs
playbook-sync.yml with the extra vars the round deploy passed."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

from utils.tests.swarm import deploy as swarm_deploy
from utils.tests.swarm import sync as swarm_sync
from utils.tests.swarm.matrix import DEPLOY_EXTRAS_FILE

PLANNER = "cli.administration.deploy.development.inventory.plan_dev_inventory_matrix"
DEPLOY_IMAGE_TAG = "cli.administration.deploy.development.deploy.run.deploy_image_tag"
ANSIBLE_PLAYBOOK = "cli.administration.deploy.dedicated.runner.deploy_ansible_playbook"
APP = "web-app-demo"
DEPLOY_ENV = {
    "INFINITO_IMAGE": "ghcr.io/infinito-nexus/core:ci-0",
    "SWARM_LAB_NETWORK": "demo-swarm-lab",
    "MGR": "demo-swarm-mgr-01",
    "WRK1": "demo-swarm-wrk-01",
    "WRK2": "demo-swarm-wrk-02",
}


def _plan(*inv_dirs: str) -> list[tuple]:
    return [(index, inv_dir, {}, [], ()) for index, inv_dir in enumerate(inv_dirs)]


class TestRoundInventory(unittest.TestCase):
    def test_a_multi_variant_app_syncs_the_round_of_its_variant(self) -> None:
        with mock.patch(PLANNER, return_value=_plan("/b-0", "/b-1")) as planner:
            inv_dir = swarm_sync.round_inventory(app_id=APP, variant=1, base_dir="/b")
        self.assertEqual(inv_dir, Path("/b-1"))
        self.assertEqual(planner.call_args.kwargs["primary_apps"], [APP])
        self.assertEqual(planner.call_args.kwargs["base_inventory_dir"], "/b")

    def test_a_single_variant_app_syncs_the_unsuffixed_inventory(self) -> None:
        with mock.patch(PLANNER, return_value=_plan("/b")):
            inv_dir = swarm_sync.round_inventory(app_id=APP, variant=0, base_dir="/b")
        self.assertEqual(inv_dir, Path("/b"))

    def test_a_variant_the_app_does_not_have_stops(self) -> None:
        with (
            mock.patch(PLANNER, return_value=_plan("/b")),
            self.assertRaises(SystemExit) as stop,
        ):
            swarm_sync.round_inventory(app_id=APP, variant=2, base_dir="/b")
        self.assertIn("variant 2", str(stop.exception))


class TestMain(unittest.TestCase):
    def _main(self, *, with_devices: bool) -> tuple[mock.MagicMock, Path]:
        with tempfile.TemporaryDirectory() as tmp:
            inv_dir = Path(tmp) / "inv"
            inv_dir.mkdir()
            if with_devices:
                (inv_dir / "devices.yml").write_text("all: {}\n")
            with (
                mock.patch.dict(os.environ, {"INFINITO_INVENTORY_DIR": tmp}),
                mock.patch.object(
                    swarm_sync, "round_inventory", return_value=inv_dir
                ) as resolve,
                mock.patch.object(swarm_deploy, "sync_role", return_value=0) as run,
            ):
                swarm_sync.main(["--app", APP, "--variant", "0"])
            self.assertEqual(resolve.call_args.kwargs["base_dir"], tmp)
            return run, inv_dir

    def test_the_round_inventory_and_its_deploy_extras_reach_the_sync(self) -> None:
        run, inv_dir = self._main(with_devices=True)
        self.assertEqual(
            run.call_args.kwargs,
            {
                "app_id": APP,
                "inv_dir": str(inv_dir),
                "extras_path": str(inv_dir / DEPLOY_EXTRAS_FILE),
                "round_index": 0,
            },
        )

    def test_a_missing_round_inventory_stops_before_ansible(self) -> None:
        with self.assertRaises(SystemExit) as stop:
            self._main(with_devices=False)
        self.assertIn("devices.yml", str(stop.exception))

    def test_an_app_id_ansible_would_read_as_an_option_is_refused(self) -> None:
        for app in ("-lall", "web-app-demo,svc-db-postgres"):
            with (
                self.subTest(app=app),
                mock.patch.object(swarm_sync, "round_inventory") as resolve,
                self.assertRaises(SystemExit),
            ):
                swarm_sync.main([f"--app={app}", "--variant", "0"])
            resolve.assert_not_called()


@mock.patch.dict(os.environ, DEPLOY_ENV)
@mock.patch(DEPLOY_IMAGE_TAG, return_value="ci-0")
@mock.patch(ANSIBLE_PLAYBOOK, return_value="/venv/bin/ansible-playbook")
class TestSyncRole(unittest.TestCase):
    def _sync(self) -> Any:
        with mock.patch.object(swarm_deploy, "run_step", return_value=0) as run:
            rc = swarm_deploy.sync_role(
                app_id=APP,
                inv_dir="/inv-1",
                extras_path="/inv-1/extras.deploy.yml",
                round_index=1,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_count, 1)
        return run.call_args

    @staticmethod
    def _extra_vars(cmd: list[str]) -> list[str]:
        return [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-e"]

    def test_only_the_hosts_of_the_app_group_run_playbook_sync(self, *_) -> None:
        cmd = self._sync().kwargs["cmd"]
        self.assertEqual(
            cmd[:4],
            [
                "/venv/bin/ansible-playbook",
                "-i",
                "/inv-1/devices.yml",
                "playbook-sync.yml",
            ],
        )
        self.assertEqual(cmd[cmd.index("-l") + 1], APP)
        self.assertEqual(
            cmd[cmd.index("--vault-password-file") + 1], "/inv-1/.password"
        )

    def test_the_sync_scopes_one_role_of_the_running_cluster(self, *_) -> None:
        last = json.loads(self._extra_vars(self._sync().kwargs["cmd"])[-1])
        self.assertEqual(last, {"APPLICATIONS_WHITELIST": [APP], "sync_scope": "role"})

    def test_the_round_extras_load_in_the_deploy_order(self, *_) -> None:
        extra = self._extra_vars(self._sync().kwargs["cmd"])
        self.assertLess(
            extra.index("@inventories/development/swarm.yml"),
            extra.index("@/inv-1/extras.deploy.yml"),
        )
        self.assertIn("VARIANT_INDEX=1", extra)
        self.assertIn(f'PRIMARY_APPS=["{APP}"]', extra)

    def test_the_sync_skips_exactly_the_modes_the_deploy_skips(self, *_) -> None:
        modes = json.loads(self._extra_vars(self._sync().kwargs["cmd"])[0])
        with mock.patch.object(swarm_deploy, "run_step", return_value=0) as run:
            swarm_deploy.deploy_round(
                app_id=APP, inv_dir="/inv-1", extras_path="/x", round_index=1, total=2
            )
        deploy_cmd = run.call_args_list[-1].kwargs["cmd"]
        skipped = {
            flag.removeprefix("--skip-").upper()
            for flag in deploy_cmd
            if flag.startswith("--skip-")
        } & set(modes)
        self.assertEqual(skipped, {"CLEANUP", "BACKUP"})
        self.assertEqual(
            {mode: modes[mode] for mode in skipped}, dict.fromkeys(skipped, False)
        )

    def test_the_sync_runs_against_the_deploy_image_without_a_target_reset(
        self, *_
    ) -> None:
        call = self._sync()
        self.assertNotIn("target-reset", call.kwargs["cmd"])
        self.assertEqual(call.kwargs["env"]["APP_ID"], APP)
        self.assertEqual(call.kwargs["env"]["INFINITO_IMAGE_TAG"], "ci-0")


if __name__ == "__main__":
    unittest.main()
