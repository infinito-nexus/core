from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.tests.swarm import extend_inventory as ei


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


if __name__ == "__main__":
    unittest.main()
