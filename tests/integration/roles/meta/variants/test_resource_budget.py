"""Integration guard: no variant's deduplicated resource footprint may exceed
the host memory budget.

For every role and every entry in its ``meta/variants.yml``, the deduplicated
footprint (the role's own containers plus the shared dependencies it pulls in,
each service counted once via the shared-service logic) is summed and checked
against:

- ``mem_reservation`` total ≤ 32 GB
- ``mem_limit`` total ≤ 72 GB

Exceeding either would over-commit the host and risk an OOM kill at deploy time.
On failure, disable services in the offending variant or move them to other
variants so each variant's footprint stays under budget.

The collection/aggregation is the single shared implementation in
``utils.roles.applications.services.resources`` (also used by the ``ressources``
CLI), so this guard and the CLI never drift."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from humanfriendly import format_size, parse_size

from utils.cache.applications import get_variants
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    load_applications_from_roles_dir,
)
from utils.roles.applications.services.resources import (
    aggregate,
    collect_role_resources,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
MAX_MEM_RESERVATION = parse_size("37GB")
MAX_MEM_LIMIT = parse_size("73GB")


@dataclass(frozen=True)
class BudgetFinding:
    role: str
    variant: int
    mem_reservation: int
    mem_limit: int


def _human(value: int) -> str:
    return format_size(value, binary=False)


def _collect_findings(root: Path) -> list[BudgetFinding]:
    roles_dir = root / "roles"
    applications = load_applications_from_roles_dir(roles_dir)
    registry = build_service_registry_from_applications(applications)
    variants = get_variants(roles_dir=str(roles_dir))

    findings: list[BudgetFinding] = []
    for role, variant_list in sorted(variants.items()):
        for index, variant_config in enumerate(variant_list):
            scoped = dict(applications)
            scoped[role] = variant_config or {}
            rows: list = []
            collect_role_resources(
                role_name=role,
                applications=scoped,
                service_registry=registry,
                visited=set(),
                rows=rows,
                warnings=[],
                dedup=True,
            )
            totals = aggregate(rows)
            mem_reservation = totals["mem_reservation_bytes"] or 0
            mem_limit = totals["mem_limit_bytes"] or 0
            if mem_reservation > MAX_MEM_RESERVATION or mem_limit > MAX_MEM_LIMIT:
                findings.append(BudgetFinding(role, index, mem_reservation, mem_limit))

    findings.sort(key=lambda f: (-f.mem_limit, f.role, f.variant))
    return findings


def _finding_line(finding: BudgetFinding) -> str:
    return (
        f"{finding.role} variant {finding.variant}: "
        f"mem_reservation={_human(finding.mem_reservation)} "
        f"(max {_human(MAX_MEM_RESERVATION)}), "
        f"mem_limit={_human(finding.mem_limit)} (max {_human(MAX_MEM_LIMIT)})"
    )


class TestVariantResourceBudget(unittest.TestCase):
    def test_no_variant_exceeds_the_memory_budget(self) -> None:
        findings = _collect_findings(PROJECT_ROOT)
        if findings:
            self.fail(
                f"{len(findings)} variant(s) exceed the host memory budget "
                f"(mem_reservation {_human(MAX_MEM_RESERVATION)} / mem_limit "
                f"{_human(MAX_MEM_LIMIT)}). This budget is required to avoid an "
                "OOM kill at deploy time. Bring each variant's deduplicated "
                "footprint under budget: disable services in the offending "
                "variant, or move them into a different variant.\n"
                + "\n".join(_finding_line(f) for f in findings)
            )


if __name__ == "__main__":
    unittest.main()
