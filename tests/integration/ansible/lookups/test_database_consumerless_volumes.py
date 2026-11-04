"""Integration test: database_consumerless_volumes against the real role tree.

The unit tests hand the lookup a literal ``shared: true``. The roles declare it
as ``{{ 'svc-db-postgres' in group_names }}``, so only a render through the real
applications lookup shows whether the predicate sees the rendered boolean.
"""

from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.applications import LookupModule as ApplicationsLookup
from plugins.lookup.applications import _reset_cache_for_tests
from plugins.lookup.database_consumerless_volumes import (
    LookupModule as ConsumerlessLookup,
)

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
LEAN = ["svc-bkp-volume-2-local", "svc-db-postgres", "svc-net-tor", "web-svc-mirror"]


def _variables(applications: dict, group_names: list[str]) -> dict:
    return {
        "applications": applications,
        "users": {},
        "DOMAIN_PRIMARY": "infinito.test",
        "SYSTEM_EMAIL_DOMAIN": "infinito.test",
        "DIR_COMPOSITIONS": "/opt/compose/",
        "group_names": list(group_names),
    }


def _consumerless(group_names: list[str]) -> list[str]:
    _reset_cache_for_tests()
    applications = ApplicationsLookup()
    applications._templar = Templar(loader=DataLoader())
    merged = applications.run(
        [], variables=_variables({}, group_names), roles_dir=str(ROLES_DIR)
    )[0]
    lookup = ConsumerlessLookup()
    lookup._loader = DataLoader()
    lookup._templar = Templar(loader=lookup._loader)
    return lookup.run([], variables=_variables(merged, group_names))[0]


class TestDatabaseConsumerlessVolumesIntegration(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_the_lean_postgres_variant_leaves_its_volume_unconsumed(self) -> None:
        self.assertEqual(_consumerless(LEAN), ["postgres_data"])

    def test_a_shared_postgres_consumer_claims_the_volume(self) -> None:
        self.assertEqual(_consumerless([*LEAN, "web-app-mastodon"]), [])

    def test_a_mariadb_consumer_leaves_postgres_unconsumed(self) -> None:
        self.assertEqual(
            _consumerless([*LEAN, "svc-db-mariadb", "web-app-matomo"]),
            ["postgres_data"],
        )


if __name__ == "__main__":
    unittest.main()
