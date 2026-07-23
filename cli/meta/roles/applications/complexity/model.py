"""The per-role complexity score, its ``dna`` cluster key and ``siblings``."""

from __future__ import annotations

import hashlib
import random
from typing import TYPE_CHECKING, Any, NamedTuple

from utils.cache.applications import get_variants
from utils.github.variant_bundles import compose_bundle_counts
from utils.roles.lifecycle import tested_lifecycles
from utils.roles.meta_lookup import (
    MetaServicesShapeError,
    get_role_mode_enabled,
    get_role_test_skips,
)
from utils.roles.validation.invokable import list_invokables_by_type

from .graph import (
    build_graphs,
    build_service_registry,
    direct_dep_roles,
    is_application_role,
    resolve_transitively,
    role_has_stack,
    truth_predicate,
)

if TYPE_CHECKING:
    from pathlib import Path

TESTED_LIFECYCLES = tested_lifecycles()
"""Lifecycle stages the CI test-deploy discovery exercises, sourced from the
``INFINITO_LIFECYCLES`` value in ``default.env`` (the single source)."""


class ComplexityRow(NamedTuple):
    """One application role. The field order is the column order; legacy
    positional access (``row[0]`` … ``row[11]``) still resolves.

    The transitive fields (``services`` / ``consumed_by`` and their
    counts) are the BFS closure capped at ``max_level``; the
    ``*_direct`` fields are always the one-hop neighbours. ``weight``
    is the sum of the four numeric columns. ``dna`` is a hash of the
    role's own name unioned with its embedded services (sorted), so two
    roles covering the same service set share a dna. ``siblings`` are
    the other roles sharing that dna; ``clone`` is True for every row of
    a dna group except the heaviest one (ties broken by name), so
    sorting clones last keeps one representative per service set ahead
    of the budget cut. ``random`` is a per-row 6-digit
    nonce, rolled fresh per invocation, so tie order deliberately varies
    between runs. ``variant`` is the ``meta/variants.yml`` index this row was
    computed against, or ``None`` for a whole-role row. ``id`` and
    ``covered_by`` are set by the CLI after sorting: ``id`` is the row's
    numeric position in sort order (1-based), and ``covered_by`` is the
    ``id`` of the first earlier (green) row of a DIFFERENT role that
    embeds this row, or the sentinel ``0`` when this row is itself green
    (no real ``id`` is 0). Two variants
    of the same role never cover each other. ``row`` is the 1-based line
    number in the final rendered output (assigned last, after
    filtering), so it stays sequential even when sorting by
    ``covered_by`` scrambles ``id``. ``variants`` is the number of
    ``meta/variants.yml`` variants of the role in whole-role mode; under
    ``--variant`` each row already is a single variant, so it is ``1``.
    ``bundles`` is the number of CI jobs the row maps to in the target
    ``deploy_mode``: compose and host pack variants into size/storage
    bundles (``compose_bundle_counts`` SPOT), swarm runs one job per
    variant; under ``--variant`` it is ``1`` per row (one variant = one
    bundle). ``jobs`` is the
    running sum of ``bundles`` down the rendered rows. ``lifecycle`` is the
    role's ``meta/services.yml`` lifecycle stage (alpha/beta/pre/…).
    ``compose`` / ``swarm`` are True when the CI test-deploy matrix exercises
    the role in that mode, honouring the discovery skip logic: invokable +
    lifecycle in the tested envelope + the role's ``skip`` list. Under
    ``--variant`` ``swarm`` is per-variant (every variant deploys, so it
    tracks the role-level ``swarm`` and ``stack``).
    ``stack`` is True when the role renders its own container stack (ships a
    ``templates/*compose*.yml.j2``); host-only roles (backup, wireguard,
    swapfile) and pure service-injectors are False. ``swarm`` implies
    ``stack``: a role with no compose template of its own is never a swarm
    stack-deploy target, so ``swarm`` is forced False when ``stack`` is False.
    ``host`` mirrors the primary entity's ``modes.host.enabled`` flag (default
    True) for non-stack roles, and is forced False for a stack role: it marks
    invokable roles that configure the host instead of shipping a stack.
    ``test_compose`` / ``test_swarm`` / ``test_host`` duplicate the mode
    columns minus the role's ``meta/tests.yml`` ``skip`` list: ``modes``
    states where a role RUNS, ``skip`` deactivates TESTING a mode, and CI
    discovery filters on these ``test_*`` columns.
    ``integrated`` is False when the row's direct service map keeps no
    foreign provider enabled (the role deploys isolated): per variant on
    variant rows, from the base ``meta/services.yml`` on whole-role rows.
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
    dna: str
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
    host: bool = False
    stack: bool = False
    test_compose: bool = False
    test_swarm: bool = False
    test_host: bool = False
    integrated: bool = True
    clone: bool = False


def _dna_hash(name: str, services: list[str]) -> str:
    members = sorted({name, *services})
    return hashlib.sha1(
        "\n".join(members).encode("utf-8"), usedforsecurity=False
    ).hexdigest()


def _attach_siblings(rows: list[ComplexityRow]) -> list[ComplexityRow]:
    by_dna: dict[str, list[ComplexityRow]] = {}
    for row in rows:
        by_dna.setdefault(row.dna, []).append(row)
    originals = {
        dna: max(group, key=lambda r: (r.weight, r.name)).name
        for dna, group in by_dna.items()
    }
    return [
        row._replace(
            siblings=sorted(r.name for r in by_dna[row.dna] if r.name != row.name),
            clone=row.name != originals[row.dna],
        )
        for row in rows
    ]


def _tested_apps(skip_mode: str, lifecycles: set[str]) -> set[str]:
    """Set of application ids the CI matrix deploys in *skip_mode*, via the
    shared ``list_invokables_by_type`` discovery (invokable + *lifecycles*
    envelope + per-mode ``skip`` opt-out). This is a project-global fact, so it
    always reads the real ``roles/`` tree regardless of a test ``roles_dir``."""
    grouped = list_invokables_by_type(lifecycles=set(lifecycles), skip_mode=skip_mode)
    return {app for apps in grouped.values() for app in apps}


def _role_test_skips(roles_dir: Path, name: str) -> list[str]:
    """The role's ``meta/tests.yml`` ``skip`` list; never breaks row building
    on a malformed meta file."""
    try:
        return get_role_test_skips(roles_dir / name, role_name=name)
    except MetaServicesShapeError:
        return []


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
        dna=_dna_hash(name, services),
        siblings=[],
        random=random.randint(100000, 999999),  # noqa: S311 - sort tie-breaker, not cryptographic
        variant=variant,
        integrated=any(provider != name for provider in services_direct),
    )


def compute_complexity_rows(
    roles_dir: Path,
    *,
    include_group_names: bool = True,
    max_level: int | None = None,
    deploy_mode: str = "compose",
    lifecycles: set[str] | None = None,
) -> list[ComplexityRow]:
    tested = set(lifecycles) if lifecycles else set(TESTED_LIFECYCLES)
    truth = truth_predicate(include_group_names=include_group_names)
    forward, reverse = build_graphs(roles_dir, truth=truth)
    variants = get_variants(roles_dir=roles_dir)
    names = [
        role_dir.name
        for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir())
        if is_application_role(role_dir)
    ]
    if deploy_mode == "swarm":
        bundles = {name: len(variants.get(name) or []) or 1 for name in names}
    else:
        bundles = compose_bundle_counts(names, variants, roles_dir=roles_dir)
    compose_apps = _tested_apps("compose", tested)
    swarm_apps = _tested_apps("swarm", tested)
    host_apps = _tested_apps("host", tested)

    rows = []
    for name in names:
        stack = role_has_stack(roles_dir / name)
        compose = name in compose_apps
        swarm = name in swarm_apps and stack
        host = (
            name in host_apps
            and not stack
            and get_role_mode_enabled(roles_dir / name, mode="host", role_name=name)
        )
        skips = _role_test_skips(roles_dir, name)
        rows.append(
            _build_row(name, forward, reverse, max_level)._replace(
                variants=len(variants.get(name) or []) or 1,
                bundles=bundles.get(name, 1),
                lifecycle=_role_lifecycle(variants.get(name)),
                compose=compose,
                swarm=swarm,
                stack=stack,
                host=host,
                test_compose=compose and "compose" not in skips,
                test_swarm=swarm and "swarm" not in skips,
                test_host=host and "host" not in skips,
            )
        )
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
    lifecycles: set[str] | None = None,
) -> list[ComplexityRow]:
    """One row per ``meta/variants.yml`` variant of every application role.

    Each row recomputes the role's embedded (forward) service deps from
    that variant's merged ``services`` map, so toggling a sidecar off in a
    variant drops it from the variant's ``embeds``/``weight``. The consumer
    (reverse) side is the variant-independent role-level graph: who else in
    the catalog embeds this role does not change with the role's own
    variant selection.
    """
    tested = set(lifecycles) if lifecycles else set(TESTED_LIFECYCLES)
    truth = truth_predicate(include_group_names=include_group_names)
    forward, reverse = build_graphs(roles_dir, truth=truth)
    registry = build_service_registry(roles_dir)
    variants = get_variants(roles_dir=roles_dir)
    compose_apps = _tested_apps("compose", tested)
    swarm_apps = _tested_apps("swarm", tested)
    host_apps = _tested_apps("host", tested)

    rows: list[ComplexityRow] = []
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        if not is_application_role(role_dir):
            continue
        name = role_dir.name
        lifecycle = _role_lifecycle(variants.get(name))
        compose = name in compose_apps
        swarm_role = name in swarm_apps
        stack = role_has_stack(role_dir)
        host = (
            name in host_apps
            and not stack
            and get_role_mode_enabled(role_dir, mode="host", role_name=name)
        )
        skips = _role_test_skips(roles_dir, name)
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
                    swarm=swarm_role and stack,
                    stack=stack,
                    host=host,
                    test_compose=compose and "compose" not in skips,
                    test_swarm=swarm_role and stack and "swarm" not in skips,
                    test_host=host and "host" not in skips,
                )
            )
    return _attach_siblings(rows)
