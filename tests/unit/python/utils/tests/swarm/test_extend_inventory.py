from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.tests.swarm import extend_inventory as ei
from utils.tests.swarm import matrix


class TestBackupLegGating(unittest.TestCase):
    def _groups(self, app_closure: list[str], nfs_closure: list[str]) -> dict:
        def _closure(role: str) -> list[str]:
            return nfs_closure if role == "svc-storage-nfs-server" else app_closure

        with tempfile.TemporaryDirectory() as td:
            inv_path = Path(td) / "devices.yml"
            env = {
                "SWARM_NAME": "t",
                "APP_ID": "svc-registry-docker",
                "INV_PATH": str(inv_path),
            }
            with (
                mock.patch.dict("os.environ", env),
                mock.patch.object(ei, "derive_includes", side_effect=_closure),
                mock.patch.object(ei, "_host_topology", return_value=[]),
                mock.patch.object(ei, "get_role_placement", return_value=""),
            ):
                ei.main()
            return ei.load_yaml_any(str(inv_path))["all"]["children"]

    def test_all_legs_skipped_when_their_inducer_prunes_them(self):
        children = self._groups(["svc-registry-docker"], ["svc-storage-nfs-server"])
        self.assertNotIn("svc-bkp-volume-2-local", children)
        self.assertNotIn("svc-bkp-secrets-2-local", children)
        self.assertNotIn("svc-bkp-nfs-2-local", children)

    def test_app_legs_follow_app_closure(self):
        children = self._groups(
            [
                "svc-registry-docker",
                "svc-bkp-volume-2-local",
                "svc-bkp-secrets-2-local",
            ],
            ["svc-storage-nfs-server"],
        )
        self.assertIn("svc-bkp-volume-2-local", children)
        self.assertIn("svc-bkp-secrets-2-local", children)
        self.assertNotIn("svc-bkp-nfs-2-local", children)

    def test_nfs_leg_follows_nfs_server_closure(self):
        children = self._groups(
            ["svc-registry-docker"],
            ["svc-storage-nfs-server", "svc-bkp-nfs-2-local"],
        )
        self.assertIn("svc-bkp-nfs-2-local", children)
        self.assertNotIn("svc-bkp-volume-2-local", children)


class TestBackupHostNetworkMode(unittest.TestCase):
    def _backup_vars(self, seeded: dict) -> dict:
        with tempfile.TemporaryDirectory() as td:
            inv_path = Path(td) / "devices.yml"
            vars_path = Path(td) / "host_vars" / f"{ei._BACKUP}.yml"
            vars_path.parent.mkdir()
            ei.dump_yaml(str(vars_path), seeded)
            env = {
                "SWARM_NAME": "t",
                "APP_ID": "svc-registry-docker",
                "INV_PATH": str(inv_path),
            }
            with (
                mock.patch.dict("os.environ", env),
                mock.patch.object(ei, "derive_includes", return_value=[]),
                mock.patch.object(ei, "_host_topology", return_value=[]),
                mock.patch.object(ei, "get_role_placement", return_value=""),
            ):
                ei.main()
            return ei.load_yaml_any(str(vars_path))

    def test_manager_network_mode_is_dropped_from_the_backup_copy(self):
        self.assertEqual(
            self._backup_vars({"NETWORK_MODE": "multi", "keep": 1}), {"keep": 1}
        )

    def test_backup_vars_without_network_mode_stay_untouched(self):
        self.assertEqual(self._backup_vars({"keep": 1}), {"keep": 1})

    def test_a_mode_a_later_mirror_copied_back_is_dropped_again(self):
        with tempfile.TemporaryDirectory() as td:
            vars_path = Path(td) / "host_vars" / f"{ei._BACKUP}.yml"
            vars_path.parent.mkdir()
            ei.dump_yaml(str(vars_path), {"NETWORK_MODE": "multi", "keep": 1})

            ei.drop_backup_network_mode(td)

            self.assertEqual(ei.load_yaml_any(str(vars_path)), {"keep": 1})

    def test_the_backup_deploy_runs_on_host_vars_without_a_network_mode(self):
        seen: dict = {}
        with tempfile.TemporaryDirectory() as td:
            vars_path = Path(td) / "host_vars" / f"{ei._BACKUP}.yml"
            vars_path.parent.mkdir()
            ei.dump_yaml(str(vars_path), {"NETWORK_MODE": "multi", "keep": 1})

            def deploy(**_kwargs):
                seen.update(ei.load_yaml_any(str(vars_path)))
                return 0

            with mock.patch.object(matrix, "_run", side_effect=deploy):
                matrix._deploy_backup_host(
                    app_id="web-app-meta", inv_dir=td, extras_path="extras.yml"
                )

        self.assertEqual(seen, {"keep": 1})


class TestSandboxWorkerLabelling(unittest.TestCase):
    def _workers(self, kata_enabled: object) -> tuple[str, ...]:
        apps = {"an-app": {"services": {"kata": {"enabled": kata_enabled}}}}
        with mock.patch.object(ei, "applications_for_round", return_value=apps):
            return ei._sandbox_workers("an-app")

    def test_a_sandboxed_app_labels_every_worker(self):
        self.assertEqual(self._workers(True), ei._WORKERS)

    def test_a_plain_app_leaves_one_worker_unlabelled(self):
        self.assertEqual(self._workers(None), ei._WORKERS[-1:])
        self.assertEqual(self._workers(False), ei._WORKERS[-1:])

    def test_an_app_without_a_kata_service_leaves_one_worker(self):
        with mock.patch.object(ei, "applications_for_round", return_value={}):
            self.assertEqual(ei._sandbox_workers("absent"), ei._WORKERS[-1:])


class TestLabShape(unittest.TestCase):
    def test_standalone_keeps_one_manager_and_two_workers(self):
        managers, workers = ei.lab_shape("standalone", prefix="t-")
        self.assertEqual(managers, ("t-swarm-mgr-01",))
        self.assertEqual(workers, ("t-swarm-wrk-01", "t-swarm-wrk-02"))

    def test_ha_has_three_managers_and_one_spare_worker(self):
        managers, workers = ei.lab_shape("ha", prefix="t-")
        self.assertEqual(
            managers, ("t-swarm-mgr-01", "t-swarm-mgr-02", "t-swarm-mgr-03")
        )
        self.assertEqual(workers, ("t-swarm-wrk-01",))

    def test_unknown_shape_fails(self):
        with self.assertRaises(SystemExit):
            ei.lab_shape("five", prefix="")


class TestHaTopology(unittest.TestCase):
    managers = ("m1", "m2", "m3")
    workers = ("w1",)

    def _hosts(self, group: str, pairs: list[tuple[str, str]]) -> set[str]:
        return {host for g, host in pairs if g == group}

    def test_every_manager_joins_the_manager_group(self):
        with mock.patch.object(ei, "get_role_placement", return_value=""):
            pairs = ei._host_topology("web-app-x", self.managers, self.workers)
        self.assertEqual(self._hosts("svc-swarm-manager", pairs), set(self.managers))
        self.assertEqual(
            self._hosts("svc-swarm-node", pairs), {*self.managers, *self.workers}
        )
        self.assertEqual(self._hosts("web-app-x", pairs), {"m1", "m2", "m3", "w1"})

    def test_a_manager_placed_app_stays_on_the_stack_host(self):
        with mock.patch.object(ei, "get_role_placement", return_value="manager"):
            pairs = ei._host_topology("web-app-x", self.managers, self.workers)
        self.assertEqual(self._hosts("web-app-x", pairs), {"m1"})

    def test_ha_engines_land_on_every_manager(self):
        with (
            mock.patch.object(
                ei, "derive_includes", return_value=["svc-db-postgres", "svc-x"]
            ),
            mock.patch.object(ei, "get_role_placement", return_value="manager"),
        ):
            pairs = ei._placement_dep_groups("web-app-x", self.managers)
        self.assertEqual(self._hosts("svc-db-postgres", pairs), set(self.managers))
        self.assertEqual(self._hosts("svc-x", pairs), {"m1"})

    def test_standalone_engines_stay_on_the_first_manager(self):
        with (
            mock.patch.object(ei, "derive_includes", return_value=["svc-db-postgres"]),
            mock.patch.object(ei, "get_role_placement", return_value="manager"),
        ):
            pairs = ei._placement_dep_groups("web-app-x", ("m1",))
        self.assertEqual(self._hosts("svc-db-postgres", pairs), {"m1"})


if __name__ == "__main__":
    unittest.main()
