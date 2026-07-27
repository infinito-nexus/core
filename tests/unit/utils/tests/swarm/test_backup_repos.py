from __future__ import annotations

import unittest
from unittest import mock

from utils.tests.swarm import backup_repos as br


class TestBackupProviderDerivation(unittest.TestCase):
    _MGR = "192.168.244.3"
    _NFS = "192.168.244.2"

    def _providers(self, app_closure: list[str]) -> list[str]:
        def _closure(role: str, *, variants: dict[str, int]) -> list[str]:
            if role == "svc-storage-nfs-server":
                return ["svc-storage-nfs-server", "svc-bkp-nfs-2-local"]
            return app_closure

        with mock.patch.object(br, "derive_includes", side_effect=_closure):
            return br.backup_provider_ips(
                app_id="svc-dns-unbound",
                variants={"svc-dns-unbound": 0},
                manager=self._MGR,
                nfs_server=self._NFS,
            )

    def test_manager_is_no_provider_without_a_manager_side_backup_role(self):
        """svc-bkp-remote-2-local/templates/script.sh.j2 counts one error per
        provider and exits 1 if any failed: a manager whose closure carries no
        backup role never ran user-backup, so it rejects the pull key and the
        whole unit fails, taking the drill's [4/9] step down with it."""
        self.assertEqual(self._providers(["svc-dns-unbound"]), [self._NFS])

    def test_manager_is_a_provider_when_its_backup_role_is_in_closure(self):
        self.assertEqual(
            self._providers(
                [
                    "svc-db-rabbitmq",
                    "svc-bkp-volume-2-local",
                    "svc-bkp-secrets-2-local",
                ]
            ),
            [self._MGR, self._NFS],
        )


if __name__ == "__main__":
    unittest.main()
