"""Semaphore joins a round only as its primary app or through the primary app's declared variant."""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from typing import ClassVar

from cli.administration.deploy.development.inventory.planner import (
    plan_dev_inventory_matrix,
)
from utils.cache.applications import get_variants
from utils.cache.files import PROJECT_ROOT
from utils.roles.applications.variants import SEMAPHORE_SERVICE_KEY
from utils.tests.swarm.derive_includes import derive_includes

_ROLES_DIR = str(PROJECT_ROOT / "roles")
_HOST = "web-app-semaphore"


def _declared(primary: str, payload: Mapping) -> bool:
    entry = (payload.get("services") or {}).get(SEMAPHORE_SERVICE_KEY)
    return primary == _HOST or (
        isinstance(entry, Mapping) and entry.get("enabled") is True
    )


class TestSemaphoreRidesThePrimaryOnly(unittest.TestCase):
    PRIMARIES: ClassVar[tuple[str, ...]] = (
        "web-app-chess",
        "svc-db-mariadb",
        _HOST,
    )

    def test_semaphore_joins_exactly_the_declared_round(self) -> None:
        variants = get_variants(roles_dir=_ROLES_DIR, readonly=True)
        for primary in self.PRIMARIES:
            plan = plan_dev_inventory_matrix(
                roles_dir=_ROLES_DIR,
                primary_apps=[primary],
                base_inventory_dir="/tmp/semaphore-rides-the-primary-only",
            )
            for round_index, _inv, round_variants, include, *_ in plan:
                declared = _declared(
                    primary, variants[primary][round_variants[primary]]
                )
                swarm = derive_includes(primary, variants=round_variants)
                with self.subTest(primary=primary, round=round_index):
                    self.assertEqual(
                        _HOST in include,
                        declared,
                        f"{primary}#{round_index}: the planned round must deploy "
                        f"{_HOST} exactly when it is the primary app or the "
                        f"primary's own variant declares it; every role's "
                        f"group-gated `semaphore` entry must not pull it in",
                    )
                    self.assertEqual(
                        _HOST in swarm,
                        declared,
                        f"{primary}#{round_index}: the swarm include set must agree "
                        f"with the planned round on {_HOST}",
                    )


if __name__ == "__main__":
    unittest.main()
