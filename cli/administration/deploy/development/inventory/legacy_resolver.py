"""Default (non-variant) include resolution for the matrix planner.

When NO primary app ships a `meta/variants.yml`, the planner falls back
to this path — the `CombinedResolver` walks `dependencies` and
`shared:`-edges in the variant-merged services map and Jinja flags are
evaluated at deploy time against `group_names`. `run_after` is NOT
followed for inclusion (it is a pure ordering hint), so a variant that
disables a service does not get the provider re-added through the
ordering edge. This module owns the two helpers that path needs and
nothing else; the variant-only path lives in `.variants`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from utils.cache.applications import get_variants
from utils.cache.base import _deep_merge
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _build_services_overrides_for_round(
    *,
    roles_dir: str,
    round_index: int,
    primary_app_variants: Mapping[str, int],
) -> dict[str, dict]:
    """For every role with `meta/variants.yml`, return the services map
    that results from merging the round's variant payload onto the
    role's on-disk `meta/services.yml`.

    Apps in `primary_app_variants` use the supplied (already clamped)
    index. Other roles with their own variants clamp `round_index` to
    their own variant count. Roles without variants are absent from the
    result so the resolver falls through to its disk-read path.

    The merged map is what the inventory ALSO bakes into host_vars, so
    feeding the same dict into `CombinedResolver(services_overrides=...)`
    eliminates the topology-vs-host_vars drift that variant-blind
    resolution produced.
    """
    variants_per_app = get_variants(roles_dir=roles_dir)
    overrides: dict[str, dict] = {}
    roles_path = Path(roles_dir)
    for role_name, variant_list in variants_per_app.items():
        if not variant_list:
            continue
        variant_count = max(1, len(variant_list))
        if role_name in primary_app_variants:
            idx = primary_app_variants[role_name]
        else:
            idx = round_index if round_index < variant_count else 0
        if not 0 <= idx < len(variant_list):
            idx = 0
        variant_payload = variant_list[idx] if variant_list else {}
        if not isinstance(variant_payload, Mapping):
            variant_payload = {}
        variant_services = variant_payload.get("services", {})
        if not isinstance(variant_services, Mapping):
            continue
        services_path = roles_path / role_name / ROLE_FILE_META_SERVICES
        if not services_path.exists():
            continue
        try:
            base_services = load_yaml_any(services_path) or {}
        except Exception:  # noqa: S112  best-effort iteration over role files; skip malformed input
            continue
        if not isinstance(base_services, Mapping):
            continue
        merged = _deep_merge(dict(base_services), dict(variant_services))
        if isinstance(merged, dict):
            overrides[role_name] = merged
    return overrides


def _resolve_round_include(
    *,
    primary_apps: Sequence[str],
    services_overrides: dict[str, dict],
) -> tuple[str, ...]:
    """Resolve transitive prerequisites for each primary app under a
    round's variant-merged services map. Returns the full include set
    in stable order (deps first per primary, primary last; primaries
    iterated in the user-provided order).

    The resolver import is deferred so the host-side import surface
    stays lean for callers that never need the variant-aware planner
    (e.g. lint/validation).
    """
    from cli.meta.roles.applications.resolution.combined.resolver import (
        CombinedResolver,
    )

    resolver = CombinedResolver(
        services_overrides=services_overrides, follow_run_after=False
    )
    out: list[str] = []
    seen: set[str] = set()
    for app_id in primary_apps:
        deps = resolver.resolve(app_id)
        for dep in deps:
            if dep != app_id and dep not in seen:
                out.append(dep)
                seen.add(dep)
        if app_id not in seen:
            out.append(app_id)
            seen.add(app_id)
    return tuple(out)
