"""Integration guard: no variant's deduplicated resource footprint may exceed
the host memory budget.

For every role and every entry in its ``meta/variants.yml``, the deduplicated
footprint (the role's own containers plus the shared dependencies it pulls in,
each service counted once via the shared-service logic) is summed and checked
against the budget below. Every role that ships variants runs the variant
:func:`utils.roles.applications.variants.active_variants_for_round` assigns it
for that round: the round index, falling back to variant 0 when it has fewer,
unless a ``# variant-pin:`` of a role the round includes forces a different
one. That is the combination a matrix round actually deploys: a dependency
sized for the production model tier is not what the round runs.
``meta/services.yml`` only supplies the roles that declare no variant at all.

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

import textwrap
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from humanfriendly import format_size, parse_size

from cli.meta.roles.applications.resolution.combined import repo_paths
from utils.annotations.suppress import suppressed_line_numbers
from utils.cache.applications import get_variants
from utils.cache.files import read_text
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    load_applications_from_roles_dir,
)
from utils.roles.applications.services.resources import (
    aggregate,
    collect_role_resources,
)
from utils.roles.applications.variant_pins import RECIPROCAL
from utils.roles.applications.variants import active_variants_for_round
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
MAX_MEM_RESERVATION = parse_size("32GB")
MAX_MEM_LIMIT = parse_size("64GB")

MEM_LIMIT_RULE = "mem-limit-budget"

PIN_SUBJECT = "web-app-budget-subject"
PIN_PARTNER = "web-app-budget-partner"


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
    return [range(start, end) for start, end in zip(starts, bounds, strict=True)]


def _marked_variants() -> set[tuple[str, int]]:
    """Every ``(role, variant index)`` whose variants file carries the marker."""
    marked: set[tuple[str, int]] = set()
    for path in sorted(ROLES_DIR.glob(f"*/{ROLE_FILE_META_VARIANTS}")):
        lines = read_text(str(path)).splitlines()
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
    path = ROLES_DIR / role / ROLE_FILE_META_VARIANTS
    if not path.is_file():
        return ""
    lines = read_text(str(path)).splitlines()
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
            active = active_variants_for_round(
                roles_dir=str(roles_dir),
                round_index=index,
                primary_app_variants={role: index},
                variants_per_app=variants,
            )
            for dep_role, dep_index in active.items():
                scoped[dep_role] = variants[dep_role][dep_index] or {}
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


def _write_pinned_partner_tree(root: Path, pin: str) -> None:
    """Write a roles tree whose subject round 1 exceeds the reservation cap
    only when the partner runs its heavy variant 0 instead of the round index.

    Args:
        root: directory the ``roles/`` tree is written under.
        pin: the line above the subject's partner entry in its variant 1,
            ``""`` for none.
    """
    files = {
        f"{PIN_SUBJECT}/{ROLE_FILE_VARS_MAIN}": f"application_id: {PIN_SUBJECT}\n",
        f"{PIN_SUBJECT}/{ROLE_FILE_META_SERVICES}": textwrap.dedent("""\
            budget-subject:
              image: subject
              mem_reservation: 20GB
              mem_limit: 24GB
            budget-partner:
              enabled: false
              shared: true
            """),
        f"{PIN_SUBJECT}/{ROLE_FILE_META_VARIANTS}": textwrap.dedent(f"""\
            - {{}}
            - services:
                {pin}
                budget-partner:
                  enabled: true
            """),
        f"{PIN_PARTNER}/{ROLE_FILE_VARS_MAIN}": f"application_id: {PIN_PARTNER}\n",
        f"{PIN_PARTNER}/{ROLE_FILE_META_SERVICES}": textwrap.dedent(f"""\
            budget-partner:
              image: partner
              shared: true
              mem_reservation: 1GB
              mem_limit: 2GB
            budget-subject:
              enabled: "{{{{ '{PIN_SUBJECT}' in group_names }}}}"
            """),
        f"{PIN_PARTNER}/{ROLE_FILE_META_VARIANTS}": textwrap.dedent("""\
            - services:
                budget-partner:
                  mem_reservation: 20GB
                  mem_limit: 24GB
                budget-subject:
                  enabled: true
            - {}
            """),
    }
    for relative, body in files.items():
        path = root / "roles" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


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


class TestPinnedPartnerBudget(unittest.TestCase):
    def _tree(self, pin: str) -> Path:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _write_pinned_partner_tree(root, pin)
        resolver_root = patch.object(repo_paths, "PROJECT_ROOT", root)
        resolver_root.start()
        self.addCleanup(resolver_root.stop)
        return root

    def test_a_pin_moving_a_partner_over_the_cap_is_reported(self) -> None:
        for target in ("0", RECIPROCAL):
            with self.subTest(target=target):
                root = self._tree(f"# variant-pin: {PIN_PARTNER}#{target}")
                self.assertEqual(
                    [
                        (f.role, f.variant, f.mem_reservation)
                        for f in _collect_findings(root)
                    ],
                    [(PIN_SUBJECT, 1, parse_size("40GB"))],
                )

    def test_without_the_pin_the_round_index_composition_fits(self) -> None:
        measured = {(m.role, m.variant): m for m in _measure(self._tree(""))}
        self.assertEqual(measured[(PIN_SUBJECT, 1)].mem_reservation, parse_size("21GB"))
        self.assertFalse(
            [m for m in measured.values() if m.over_reservation or m.over_limit]
        )


if __name__ == "__main__":
    unittest.main()
