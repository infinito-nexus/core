"""Lint guard: variant 0 is the role's baseline closure, every other
variant's closure MUST be a subset of it.

Background
==========
The matrix-deploy mechanism (docs/contributing/design/variants.md)
treats variant 0 as the all-flags-true baseline and lets later
variants pin individual dynamic flags to ``false`` to exercise the
out-of-group_names branch (see ``test_coverage.py``). The closure
of a "minimal" variant therefore SHRINKS relative to variant 0 —
it drops deps that the disabled flags would otherwise auto-include.
That shrinkage is by design.

What is NOT acceptable is a non-baseline variant that adds a dep
variant 0 does not have, because that breaks the "v0 is the maximal
deploy footprint" contract every other tooling layer relies on
(round-0 baseline include, deploy planner, dep-aware purge between
rounds, etc.).

Detection
=========
For each application with ``len(variants) > 1``:

1. Compute ``closure_v = transitive set of role IDs`` reachable from
   the application via ``run_after`` plus shared-service auto-include
   (``services.<svc>.enabled is True AND shared is True``), using
   variant ``v`` for the application's own services and variant 0 for
   every recursive dep (deps don't track the parent's variant).
2. If any non-baseline closure (``v > 0``) is NOT a subset of the
   baseline closure (``v = 0``), record the divergence as an offender.
   Empty closures trivially satisfy subset and are accepted.
"""

from __future__ import annotations

import contextlib
import unittest
from typing import TYPE_CHECKING, Any

from utils.cache.applications import get_variants
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    load_run_after_from_roles_dir,
    resolve_service_dependency_roles_from_config,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR: Path = PROJECT_ROOT / "roles"


def _direct_deps(
    role: str,
    config: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    roles_dir: Path,
) -> set[str]:
    deps = set(resolve_service_dependency_roles_from_config(config, registry))
    # Shape errors in run_after are caught by their own lint; here we
    # treat the role as having no run_after so this lint stays focused
    # on variant divergence.
    with contextlib.suppress(Exception):
        deps.update(load_run_after_from_roles_dir(roles_dir, role))
    return deps


def _closure(
    role: str,
    config: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    roles_dir: Path,
    variants_by_app: dict[str, list[Any]],
) -> frozenset[str]:
    visited: set[str] = set()
    stack: list[tuple[str, dict[str, Any]]] = [(role, config)]
    while stack:
        current_role, current_config = stack.pop()
        for dep in _direct_deps(current_role, current_config, registry, roles_dir):
            if dep == role or dep in visited:
                continue
            visited.add(dep)
            dep_variants = variants_by_app.get(dep)
            dep_config = dep_variants[0] if dep_variants else {}
            stack.append((dep, dep_config))
    return frozenset(visited)


class TestVariantDepConsistency(unittest.TestCase):
    """Non-baseline variant closures MUST be subsets of variant 0's closure."""

    def test_non_baseline_variant_closures_are_subsets_of_baseline(self) -> None:
        variants_by_app = get_variants(roles_dir=str(ROLES_DIR))

        # Service registry is built from variant 0 of every app — this
        # is the canonical view used to resolve which role a service
        # key points to. Variant overrides can flip enabled/shared but
        # cannot change what role provides a given service key.
        defaults = {
            app: variants[0] for app, variants in variants_by_app.items() if variants
        }
        registry = build_service_registry_from_applications(defaults)

        offenders: dict[str, list[tuple[int, list[str]]]] = {}
        for app, variants in sorted(variants_by_app.items()):
            if len(variants) <= 1:
                continue
            closures = [
                _closure(app, variant, registry, ROLES_DIR, variants_by_app)
                for variant in variants
            ]
            baseline = closures[0]
            # A non-baseline variant may shrink the closure (minimal /
            # standalone variants pin dynamic flags to false) but it
            # MUST NOT introduce a dep that the baseline lacks. Empty
            # closures are subsets of anything and pass trivially.
            if any(not closure.issubset(baseline) for closure in closures[1:]):
                offenders[app] = [
                    (index, sorted(closure)) for index, closure in enumerate(closures)
                ]

        if not offenders:
            return

        lines = [
            f"{len(offenders)} application(s) carry non-baseline variants "
            "whose recursive dep closure is NOT a subset of variant 0's "
            "closure. Variant 0 is the role's maximal deploy footprint; "
            "later variants may only DROP deps, never introduce new ones, "
            "so the round-0 baseline include and the dep-aware purge "
            "logic stay consistent across the matrix.",
            "",
            "Background: docs/contributing/design/variants.md",
            "",
        ]
        for app, items in sorted(offenders.items()):
            lines.append(f"  - {app}:")
            for index, closure in items:
                rendered = ", ".join(closure) if closure else "(empty)"
                lines.append(f"      * variant {index}: {rendered}")
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
