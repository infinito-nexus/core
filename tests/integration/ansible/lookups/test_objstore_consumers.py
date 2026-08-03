"""Integration test: objstore_consumers against the real merged config.

The unit tests stub the ``objstore`` lookup, so they only pin this lookup's
own predicate. This one runs it through the real Ansible plugin loader over
the real role tree, which is what the seaweedfs role does at render time.
"""

from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.filter.seaweedfs import VOLUME_GROW_BATCH, volume_slots
from plugins.lookup.applications import (
    LookupModule as ApplicationsLookup,
)
from plugins.lookup.applications import (
    _reset_cache_for_tests,
)
from plugins.lookup.objstore_consumers import LookupModule as ObjstoreConsumersLookup
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
PROVIDER = "web-app-seaweedfs"
DECLARED_CONSUMER = "web-app-matrix"
OVERRIDE_CONSUMER = "web-app-hugo"
NON_CONSUMER = "svc-db-postgres"
DECLARED_GROUPS = [DECLARED_CONSUMER, PROVIDER, NON_CONSUMER, "svc-swarm-manager"]
OVERRIDE_GROUPS = [OVERRIDE_CONSUMER, PROVIDER]
ALL_GROUPS = sorted(set(DECLARED_GROUPS) | set(OVERRIDE_GROUPS))
OVERRIDE = {
    OVERRIDE_CONSUMER: {"services": {"seaweedfs": {"enabled": True, "shared": True}}}
}


def _variables(applications: dict, group_names: list[str]) -> dict:
    return {
        "applications": applications,
        "users": {},
        "DOMAIN_PRIMARY": "infinito.example",
        "SYSTEM_EMAIL_DOMAIN": "infinito.example",
        "DIR_COMPOSITIONS": "/opt/compose/",
        "group_names": list(group_names),
    }


def _consumers(applications: dict, group_names: list[str]) -> list[str]:
    lookup = ObjstoreConsumersLookup()
    lookup._loader = DataLoader()
    lookup._templar = Templar(loader=lookup._loader)
    return lookup.run(["seaweedfs"], variables=_variables(applications, group_names))[0]


class TestObjstoreConsumersIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        applications = ApplicationsLookup()
        applications._templar = Templar(loader=DataLoader())
        merged = applications.run(
            [], variables=_variables(OVERRIDE, ALL_GROUPS), roles_dir=str(ROLES_DIR)
        )[0]
        cls.declared = _consumers(merged, DECLARED_GROUPS)
        cls.override = _consumers(merged, OVERRIDE_GROUPS)

    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_multi_domain_consumer_is_the_only_declared_one(self) -> None:
        self.assertEqual(
            self.declared,
            [DECLARED_CONSUMER],
            f"{DECLARED_CONSUMER} binds seaweedfs as a shared object store and "
            "is the only role in this scenario that does. Anything else here "
            "means a consumer was dropped or an unrelated role slipped in.",
        )

    def test_override_consumer_declares_nothing_on_disk(self) -> None:
        declared = read_text(
            str(ROLES_DIR / OVERRIDE_CONSUMER / ROLE_FILE_META_SERVICES)
        )
        self.assertNotIn(
            "seaweedfs",
            declared,
            f"{OVERRIDE_CONSUMER} was picked because it declares no object "
            "store; pick another role for this test now that it does.",
        )

    def test_inventory_bound_consumer_is_the_only_override_one(self) -> None:
        self.assertEqual(
            self.override,
            [OVERRIDE_CONSUMER],
            "A store bound through the applications inventory variable alone "
            "still grants S3 write access, so it must reach the volume budget "
            "too.",
        )

    def test_provider_is_not_its_own_consumer(self) -> None:
        self.assertNotIn(PROVIDER, self.declared)
        self.assertNotIn(PROVIDER, self.override)

    def test_group_without_a_binding_is_absent(self) -> None:
        self.assertNotIn(NON_CONSUMER, self.declared)

    def test_each_scenario_budgets_more_than_the_default_collection_batch(self) -> None:
        for label, consumers in (
            ("declared", self.declared),
            ("override", self.override),
        ):
            with self.subTest(scenario=label):
                self.assertGreater(
                    volume_slots(len(consumers)),
                    VOLUME_GROW_BATCH,
                    "The first grow batch goes to the unnamed default "
                    "collection, so a budget of one batch leaves no volume for "
                    f"any named collection and every S3 PUT fails. Consumers: "
                    f"{consumers}",
                )


if __name__ == "__main__":
    unittest.main()
