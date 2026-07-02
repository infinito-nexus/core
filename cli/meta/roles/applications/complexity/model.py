"""The per-role complexity score, its ``base`` cluster key and ``siblings``."""

from __future__ import annotations

import hashlib
import random
from typing import TYPE_CHECKING, Any, NamedTuple

from utils.cache.applications import get_variant_overrides_only, get_variants
from utils.github.variant_bundles import compose_bundle_counts
from utils.roles.applications.services.variant_status import (
    deployable_variant_indices,
)
from utils.roles.validation.invokable import list_invokables_by_type

from .graph import (
    build_graphs,
    build_service_registry,
    direct_dep_roles,
    is_application_role,
    resolve_transitively,
    truth_predicate,
)

if TYPE_CHECKING:
    from pathlib import Path

TESTED_LIFECYCLES = frozenset({"alpha", "beta", "rc", "stable"})
"""Lifecycle stages the CI test-deploy discovery exercises (mirrors
``scripts/meta/resolve/apps.sh`` ``--lifecycles alpha beta rc stable``)."""


class ComplexityRow(NamedTuple):
    """One application role. The field order is the column order; legacy
    positional access (``row[0]`` … ``row[11]``) still resolves.

    The transitive fields (``services`` / ``consumed_by`` and their
    counts) are the BFS closure capped at ``max_level``; the
    ``*_direct`` fields are always the one-hop neighbours. ``weight``
    is the sum of the four numeric columns. ``base`` is a hash of the
    role's own name unioned with its embedded services (sorted), so two
    roles covering the same service set share a base. ``siblings`` are
    the other roles sharing that base. ``random`` is a per-row 6-digit
    nonce. ``variant`` is the ``meta/variants.yml`` index this row was
    computed against, or ``None`` for a whole-role row. ``id`` and
    ``covered_by`` are set by the CLI after sorting: ``id`` is the row's
    numeric position in sort order (1-based), and ``covered_by`` is the
    ``id`` of the first earlier (green) row of a DIFFERENT role that
    embeds this row, or the sentinel ``0`` when this row is itself green
    (no real ``id`` is 0). Two variants
    of the same role never cover each other. ``row`` is the 1-based line
    number in the final rendered output (assigned last, after
    filter/unique), so it stays sequential even when sorting by
    ``covered_by`` scrambles ``id``. ``variants`` is the number of
    ``meta/variants.yml`` variants of the role in whole-role mode; under
    ``--variant`` each row already is a single variant, so it is ``1``.
    ``bundles`` is the number of CI jobs the row maps to in the target
    ``deploy_mode``: compose packs variants into size/storage bundles
    (``compose_bundle_counts`` SPOT), swarm runs one per deployable variant
    (``deployable_variant_indices``); under ``--variant`` it is ``1`` per row
    (one variant = one bundle). ``jobs`` is the
    running sum of ``bundles`` down the rendered rows. ``lifecycle`` is the
    role's ``meta/services.yml`` lifecycle stage (alpha/beta/pre/…).
    ``compose`` / ``swarm`` are True when the CI test-deploy matrix exercises
    the role in that mode, honouring the discovery skip logic: invokable +
    lifecycle in the tested envelope + the role's ``skip`` list, plus, for
    ``swarm``, at least one non-all-off (deployable) variant. Under
    ``--variant`` ``swarm`` is per-variant (an all-off variant is False).
    """

    name: str
    embeds: int
    services: list[str]
    consumers: int
    consumed_by: list[str]
    embeds_direct: int
    services_direct: list[str]
    consumers_direct: int
    consumed_by_direct: list[str]
    weight: int
    base: str
    siblings: list[str]
    random: int = 0
    variant: int | None = None
    id: int = 0
    covered_by: int = 0
    row: int = -1
    variants: int = 1
    bundles: int = 1
    jobs: int = 0
    lifecycle: str = ""
    compose: bool = False
    swarm: bool = False


def _base_hash(name: str, services: list[str]) -> str:
    members = sorted({name, *services})
    return hashlib.sha1(
        "\n".join(members).encode("utf-8"), usedforsecurity=False
    ).hexdigest()


def _attach_siblings(rows: list[ComplexityRow]) -> list[ComplexityRow]:
    by_base: dict[str, list[str]] = {}
    for row in rows:
        by_base.setdefault(row.base, []).append(row.name)
    return [
        row._replace(siblings=sorted(n for n in by_base[row.base] if n != row.name))
        for row in rows
    ]


def _tested_apps(skip_mode: str) -> set[str]:
    """Set of application ids the CI matrix deploys in *skip_mode*, via the
    shared ``list_invokables_by_type`` discovery (invokable + tested-lifecycle
    + per-mode ``skip`` opt-out). This is a project-global fact, so it always
    reads the real ``roles/`` tree regardless of a test ``roles_dir``."""
    grouped = list_invokables_by_type(
        lifecycles=set(TESTED_LIFECYCLES), skip_mode=skip_mode
    )
    return {app for apps in grouped.values() for app in apps}


def _role_lifecycle(role_variants: Any) -> str:
    """The role's lifecycle stage, read from the primary ``meta/services.yml``
    entry (the only one carrying a ``lifecycle`` field). Empty when absent."""
    for variant_config in role_variants or []:
        services = (
            variant_config.get("services") if isinstance(variant_config, dict) else None
        )
        if isinstance(services, dict):
            for entry in services.values():
                if isinstance(entry, dict) and entry.get("lifecycle"):
                    return str(entry["lifecycle"])
    return ""


def _build_row(
    name: str,
    forward: dict[str, list[str]],
    reverse: dict[str, list[str]],
    max_level: int | None,
    *,
    variant: int | None = None,
) -> ComplexityRow:
    services = resolve_transitively(name, forward, max_level=max_level)
    consumers = resolve_transitively(name, reverse, max_level=max_level)
    services_direct = resolve_transitively(name, forward, max_level=1)
    consumers_direct = resolve_transitively(name, reverse, max_level=1)
    weight = (
        len(services) + len(consumers) + len(services_direct) + len(consumers_direct)
    )
    return ComplexityRow(
        name=name,
        embeds=len(services),
        services=services,
        consumers=len(consumers),
        consumed_by=consumers,
        embeds_direct=len(services_direct),
        services_direct=services_direct,
        consumers_direct=len(consumers_direct),
        consumed_by_direct=consumers_direct,
        weight=weight,
        base=_base_hash(name, services),
        siblings=[],
        random=random.randint(100000, 999999),  # noqa: S311 — display nonce, not crypto
        variant=variant,
    )


def compute_complexity_rows(
    roles_dir: Path,
    *,
    include_group_names: bool = True,
    max_level: int | None = None,
    deploy_mode: str = "compose",
) -> list[ComplexityRow]:
    truth = truth_predicate(include_group_names=include_group_names)
    forward, reverse = build_graphs(roles_dir, truth=truth)
    variants = get_variants(roles_dir=roles_dir)
    overrides = get_variant_overrides_only(roles_dir=roles_dir)
    names = [
        role_dir.name
        for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir())
        if is_application_role(role_dir)
    ]
    if deploy_mode == "swarm":
        bundles = {
            name: len(deployable_variant_indices(overrides.get(name))) for name in names
        }
    else:
        bundles = compose_bundle_counts(names, variants, roles_dir=roles_dir)
    compose_apps = _tested_apps("compose")
    swarm_apps = _tested_apps("swarm")

    rows = [
        _build_row(name, forward, reverse, max_level)._replace(
            variants=len(variants.get(name) or []) or 1,
            bundles=bundles.get(name, 1),
            lifecycle=_role_lifecycle(variants.get(name)),
            compose=name in compose_apps,
            swarm=name in swarm_apps
            and bool(deployable_variant_indices(overrides.get(name))),
        )
        for name in names
    ]
    return _attach_siblings(rows)


def _variant_services_map(variant_config: Any) -> dict[str, Any]:
    if not isinstance(variant_config, dict):
        return {}
    services = variant_config.get("services")
    return services if isinstance(services, dict) else {}


def compute_variant_complexity_rows(
    roles_dir: Path,
    *,
    include_group_names: bool = True,
    max_level: int | None = None,
) -> list[ComplexityRow]:
    """One row per ``meta/variants.yml`` variant of every application role.

    Each row recomputes the role's embedded (forward) service deps from
    that variant's merged ``services`` map, so toggling a sidecar off in a
    variant drops it from the variant's ``embeds``/``weight``. The consumer
    (reverse) side is the variant-independent role-level graph: who else in
    the catalog embeds this role does not change with the role's own
    variant selection.
    """
    truth = truth_predicate(include_group_names=include_group_names)
    forward, reverse = build_graphs(roles_dir, truth=truth)
    registry = build_service_registry(roles_dir)
    variants = get_variants(roles_dir=roles_dir)
    overrides = get_variant_overrides_only(roles_dir=roles_dir)
    compose_apps = _tested_apps("compose")
    swarm_apps = _tested_apps("swarm")

    rows: list[ComplexityRow] = []
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        if not is_application_role(role_dir):
            continue
        name = role_dir.name
        lifecycle = _role_lifecycle(variants.get(name))
        compose = name in compose_apps
        swarm_role = name in swarm_apps
        deployable = set(deployable_variant_indices(overrides.get(name)))
        for index, variant_config in enumerate(variants.get(name) or []):
            providers = direct_dep_roles(
                _variant_services_map(variant_config), registry, truth=truth
            )
            variant_forward = dict(forward)
            variant_forward[name] = providers
            rows.append(
                _build_row(
                    name, variant_forward, reverse, max_level, variant=index
                )._replace(
                    lifecycle=lifecycle,
                    compose=compose,
                    swarm=swarm_role and index in deployable,
                )
            )
    return _attach_siblings(rows)
