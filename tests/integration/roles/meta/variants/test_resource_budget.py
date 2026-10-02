"""Integration guard: no variant's deduplicated resource footprint may exceed
the host memory budget.

For every role and every entry in its ``meta/variants.yml``, the deduplicated
footprint (the role's own containers plus the shared dependencies it pulls in,
each service counted once via the shared-service logic) is summed and checked
against the budget below. Every role that ships variants is evaluated at the
same round index, falling back to variant 0 when it has fewer, because that is
the combination a matrix round actually deploys: a dependency sized for the
production model tier is not what the round runs. ``meta/services.yml`` only
supplies the roles that declare no variant at all.

- ``mem_reservation`` total ≤ 32 GB
- ``mem_limit`` total ≤ 64 GB

Exceeding either would over-commit the host and risk an OOM kill at deploy time.
On failure, disable services in the offending variant or move them to other
variants so each variant's footprint stays under budget.

A ``# nocheck: mem-limit-budget`` marker inside a variant's own entry in
``meta/variants.yml`` lets that variant exceed the ``mem_limit`` cap alone, and
only when the marker carries text; a bare marker grants nothing, and
``mem_reservation`` stays enforced for an exempt variant. ``mem_limit`` is a per-container ceiling rather than a
guarantee, so a sum of ceilings above host memory is survivable in a way an
over-committed ``mem_reservation`` is not.
``test_every_mem_limit_exemption_is_still_needed`` fails once an exempt variant
drops back under the cap, so an entry cannot outlive its cause.

The collection/aggregation is the single shared implementation in
``utils.roles.applications.services.resources`` (also used by the ``ressources``
CLI), so this guard and the CLI never drift."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from humanfriendly import format_size, parse_size

from utils.annotations.suppress import suppressed_line_numbers
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
MAX_MEM_RESERVATION = parse_size("32GB")
MAX_MEM_LIMIT = parse_size("64GB")

MEM_LIMIT_RULE = "mem-limit-budget"


@dataclass(frozen=True)
class BudgetMeasurement:
    role: str
    variant: int
    mem_reservation: int
    mem_limit: int

    @property
    def over_reservation(self) -> bool:
        return self.mem_reservation > MAX_MEM_RESERVATION

    @property
    def over_limit(self) -> bool:
        return self.mem_limit > MAX_MEM_LIMIT


def _human(value: int) -> str:
    return format_size(value, binary=False)


def _variant_spans(lines: list[str]) -> list[range]:
    """The line range each top-level list entry of a variants file occupies.

    Args:
        lines: the file's lines.

    Returns:
        One 1-based range per variant, in declaration order.
    """
    starts = [n for n, line in enumerate(lines, 1) if line.startswith("- ")]
    bounds = [*starts[1:], len(lines) + 1]
    return [range(start, end) for start, end in zip(starts, bounds)]


def _marked_variants() -> set[tuple[str, int]]:
    """Every ``(role, variant index)`` whose variants file carries the marker."""
    marked: set[tuple[str, int]] = set()
    for path in sorted(ROLES_DIR.glob("*/meta/variants.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        numbers = suppressed_line_numbers(lines, MEM_LIMIT_RULE)
        if not numbers:
            continue
        role = path.parent.parent.name
        for index, span in enumerate(_variant_spans(lines)):
            if numbers & set(span):
                marked.add((role, index))
    return marked


def _mem_limit_reason(role: str, variant: int) -> str:
    """The reason a variant's ``meta/variants.yml`` gives for exceeding mem_limit.

    Args:
        role: the role the variant belongs to.
        variant: the variant's index in ``meta/variants.yml``.

    Returns:
        The stripped text following the marker, or ``""`` when the variant
        carries none. A marker without text grants no exemption.
    """
    path = ROLES_DIR / role / "meta" / "variants.yml"
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    spans = _variant_spans(lines)
    if variant >= len(spans):
        return ""
    marked = suppressed_line_numbers(lines, MEM_LIMIT_RULE) & set(spans[variant])
    if not marked:
        return ""
    body = lines[min(marked) - 1].split(MEM_LIMIT_RULE, 1)[1]
    return body.lstrip(" :—-").strip()


def _measure(root: Path) -> list[BudgetMeasurement]:
    roles_dir = root / "roles"
    applications = load_applications_from_roles_dir(roles_dir)
    registry = build_service_registry_from_applications(applications)
    variants = get_variants(roles_dir=str(roles_dir))

    measurements: list[BudgetMeasurement] = []
    for role, variant_list in sorted(variants.items()):
        for index, variant_config in enumerate(variant_list):
            scoped = dict(applications)
            for dep_role, dep_variants in variants.items():
                if not dep_variants:
                    continue
                dep_index = index if index < len(dep_variants) else 0
                scoped[dep_role] = dep_variants[dep_index] or {}
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
                dynamic_enabled=False,
            )
            totals = aggregate(rows)
            measurements.append(
                BudgetMeasurement(
                    role,
                    index,
                    totals["mem_reservation_bytes"] or 0,
                    totals["mem_limit_bytes"] or 0,
                )
            )
    return measurements


def _collect_findings(root: Path) -> list[BudgetMeasurement]:
    findings = [
        measurement
        for measurement in _measure(root)
        if measurement.over_reservation
        or (
            measurement.over_limit
            and not _mem_limit_reason(measurement.role, measurement.variant)
        )
    ]
    findings.sort(key=lambda f: (-f.mem_limit, f.role, f.variant))
    return findings


def _finding_line(finding: BudgetMeasurement) -> str:
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

    def test_every_mem_limit_exemption_is_still_needed(self) -> None:
        measured = {(m.role, m.variant): m for m in _measure(PROJECT_ROOT)}
        stale: list[str] = []
        for role, variant in sorted(_marked_variants()):
            measurement = measured.get((role, variant))
            if measurement is None:
                stale.append(f"{role} variant {variant}: no such variant any more")
            elif not measurement.over_limit:
                stale.append(
                    f"{role} variant {variant}: mem_limit="
                    f"{_human(measurement.mem_limit)} is back within the "
                    f"{_human(MAX_MEM_LIMIT)} cap"
                )

        if stale:
            self.fail(
                f"{len(stale)} '# nocheck: {MEM_LIMIT_RULE}' marker(s) no longer "
                "buy anything. Delete each one from its meta/variants.yml so the "
                "cap guards the variant again:\n" + "\n".join(stale)
            )


if __name__ == "__main__":
    unittest.main()
