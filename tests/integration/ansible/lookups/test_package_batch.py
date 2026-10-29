"""Integration test: package_batch against the real merged config and role tree.

The host deploys the application set of a local Nextcloud deploy. The batch
must hold the ids of the supporting roles that deploy ran through
``include_role`` (none of them is an application of the host), and nothing a
role still installs itself or only a workstation runs.
"""

from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.applications import _reset_cache_for_tests
from plugins.lookup.package_batch import LookupModule as PackageBatchLookup
from utils.packages.registry import build_registry

from . import PROJECT_ROOT

APPLICATIONS = [
    "svc-bkp-secrets-2-local",
    "svc-bkp-volume-2-local",
    "svc-db-mariadb",
    "svc-db-openldap",
    "svc-db-postgres",
    "svc-db-redis",
    "web-app-keycloak",
    "web-app-nextcloud",
    "web-app-seaweedfs",
    "web-svc-cdn",
    "web-svc-collabora",
    "web-svc-coturn",
    "web-svc-logout",
]
SUPPORTING_ROLE_IDS = {
    "sys-daemon": "systemd-tools",
    "sys-openssl": "openssl",
    "sys-svc-compose": "python-yaml",
    "sys-svc-mail-msmtp": "msmtp",
    "sys-svc-nss": "nss-myhostname",
    "svc-db-openldap": "openldap-dev",
}
WORKSTATION_ID = "firefox"


def _variables(group_names: list[str]) -> dict:
    return {
        "applications": {},
        "users": {},
        "DOMAIN_PRIMARY": "infinito.test",
        "SYSTEM_EMAIL_DOMAIN": "infinito.test",
        "DIR_COMPOSITIONS": "/opt/compose/",
        "group_names": list(group_names),
    }


class TestPackageBatchIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        lookup = PackageBatchLookup()
        lookup._loader = DataLoader()
        lookup._templar = Templar(loader=lookup._loader)
        cls.batch = lookup.run([APPLICATIONS], variables=_variables(APPLICATIONS))[0]
        cls.registry = build_registry(PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_supporting_roles_are_covered(self) -> None:
        missing = {
            role: package_id
            for role, package_id in SUPPORTING_ROLE_IDS.items()
            if package_id not in self.batch
        }
        self.assertEqual(
            missing,
            {},
            "The deploy runs these roles through include_role only; the batch "
            "dropped their ids, so nothing installs them any more.",
        )

    def test_the_batch_holds_no_unbatched_id(self) -> None:
        self.assertEqual(
            [pid for pid in self.batch if not self.registry[pid].batch], []
        )

    def test_a_server_gets_no_workstation_package(self) -> None:
        self.assertNotIn(WORKSTATION_ID, self.batch)


if __name__ == "__main__":
    unittest.main()
