"""The README replay host joins a round only through the primary app's declared guide variant."""

from __future__ import annotations

import unittest
from typing import ClassVar

from cli.administration.deploy.development.inventory.planner import (
    plan_dev_inventory_matrix,
)
from utils.cache.applications import get_variants
from utils.cache.files import PROJECT_ROOT
from utils.roles.guide import declares_guide
from utils.tests.swarm.derive_includes import derive_includes

_ROLES_DIR = str(PROJECT_ROOT / "roles")
_GUIDE_HOST = "web-app-docs"


class TestGuideRidesThePrimaryOnly(unittest.TestCase):
    PRIMARIES: ClassVar[tuple[str, ...]] = ("web-app-listmonk", "svc-db-mariadb")

    def test_the_guide_host_joins_exactly_the_declared_round(self) -> None:
        variants = get_variants(roles_dir=_ROLES_DIR, readonly=True)
        for primary in self.PRIMARIES:
            plan = plan_dev_inventory_matrix(
                roles_dir=_ROLES_DIR,
                primary_apps=[primary],
                base_inventory_dir="/tmp/guide-rides-the-primary-only",
            )
            for round_index, _inv, round_variants, include, *_ in plan:
                payload = variants[primary][round_variants[primary]]
                declared = declares_guide(payload.get("services") or {})
                swarm = derive_includes(primary, variants=round_variants)
                with self.subTest(primary=primary, round=round_index):
                    self.assertEqual(
                        _GUIDE_HOST in include,
                        declared,
                        f"{primary}#{round_index}: the planned round must deploy "
                        f"{_GUIDE_HOST} exactly when {primary}'s own variant declares "
                        f"it; a partner falling back to its variant 0 must not pull "
                        f"it in",
                    )
                    self.assertEqual(
                        _GUIDE_HOST in swarm,
                        declared,
                        f"{primary}#{round_index}: the swarm include set must agree "
                        f"with the planned round on {_GUIDE_HOST}",
                    )


if __name__ == "__main__":
    unittest.main()
