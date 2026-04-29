"""SPOT for development inventory creation.

Anything that wants to materialise the development inventory MUST go
through `build_dev_inventory` (single folder) or
`build_dev_inventory_matrix` (one folder per matrix-deploy round). Both
flow through `DevInventorySpec` and own:

* the SPOT vars-file (`DEV_INVENTORY_VARS_FILE`),
* per-app variant baking (each role's `meta/variants.yml` is resolved at
  build time and emitted as `applications.<app>` overrides into the
  inventory's `host_vars`, with variant 0 as the fallback for apps
  without `meta/variants.yml`),
* the vault password file.

The deploy wrapper consumes `plan_dev_inventory_matrix` to know which
folder to deploy against in each round; the planner is a pure function
so wrapper and init step compute the same plan independently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from utils.cache.applications import get_variants
from utils.cache.base import _deep_merge
from utils.cache.yaml import load_yaml_any

from .common import DEV_INVENTORY_VARS_FILE
from .mirrors import generate_ci_mirrors_file, should_use_mirrors_on_ci

if TYPE_CHECKING:
    from .compose import Compose


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
        services_path = roles_path / role_name / "meta" / "services.yml"
        if not services_path.exists():
            continue
        try:
            base_services = load_yaml_any(services_path) or {}
        except Exception:
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
    """
    # Late import keeps the host-side import surface lean for callers
    # that never need the variant-aware planner (e.g. lint/validation).
    from cli.meta.applications.resolution.combined.resolver import CombinedResolver

    resolver = CombinedResolver(services_overrides=services_overrides)
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


@dataclass(frozen=True)
class DevInventorySpec:
    """Everything `infinito create inventory` needs to materialise one
    development inventory folder.

    `extra_vars` wins over the implicit `STORAGE_CONSTRAINED` / `RUNTIME`
    overrides so callers (and tests) keep the documented "user-provided
    vars always win" behaviour without re-implementing the merge.

    `active_variants` is the per-app variant index for the round this
    folder represents. Apps absent from the mapping (or with an out-of-
    range index) fall back to variant 0. The resolved variant payload
    for every app in `include` is baked into the inventory as an
    `applications.<app>` override, so the deploy stage no longer needs
    a runtime variant selector — the inventory itself is variant-resolved.
    """

    inventory_dir: str
    include: tuple[str, ...]
    storage_constrained: bool
    runtime: str
    extra_vars: Mapping[str, Any] | None = None
    services_disabled: str = ""
    active_variants: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        if not self.include:
            raise ValueError("DevInventorySpec.include must not be empty")
        if not isinstance(self.include, tuple):
            object.__setattr__(self, "include", tuple(self.include))

    def overrides(self) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "STORAGE_CONSTRAINED": bool(self.storage_constrained),
            "RUNTIME": self.runtime,
        }
        if self.extra_vars:
            merged.update(self.extra_vars)
        return merged

    def variant_selectors(self) -> dict[str, int]:
        return dict(self.active_variants or {})

    def inventory_root(self) -> str:
        return str(self.inventory_dir).rstrip("/")


def _resolve_variant_payloads(
    *,
    roles_dir: str,
    include: Sequence[str],
    active_variants: Mapping[str, int],
) -> dict[str, Any]:
    """Return ``{app_id: variant_payload}`` for the requested round.

    Apps without `meta/variants.yml` collapse to a single empty variant
    in the loader, so this just picks variant 0 (= `meta/services.yml`
    unchanged) for them. Out-of-range indices clamp to 0.
    """
    variants_per_app = get_variants(roles_dir=roles_dir)
    resolved: dict[str, Any] = {}
    for app_id in include:
        variant_list = variants_per_app.get(app_id) or [{}]
        if not variant_list:
            continue
        index = active_variants.get(app_id, 0)
        if not 0 <= index < len(variant_list):
            index = 0
        resolved[app_id] = variant_list[index]
    return resolved


def _bake_overrides(
    *,
    base_overrides: Mapping[str, Any],
    variant_payloads: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge the per-app variant payloads under `applications:` into the
    `--vars` JSON the init step will hand to `infinito create inventory`.
    Caller-supplied `extra_vars` (already inside `base_overrides`) win
    over the variant bake when the same key is set on both sides — that
    matches the existing "user vars always win" rule."""
    merged: dict[str, Any] = dict(base_overrides)
    if not variant_payloads:
        return merged
    existing_apps = merged.get("applications")
    if not isinstance(existing_apps, Mapping):
        existing_apps = {}
    apps: dict[str, Any] = {
        app_id: payload for app_id, payload in variant_payloads.items()
    }
    # Caller-supplied `applications.*` entries deep-overlay the variant
    # payload so overrides like `applications.web-app-foo.feature_flag` from
    # `--vars` still take precedence.
    for app_id, override in existing_apps.items():
        base_payload = apps.get(app_id)
        if isinstance(base_payload, Mapping) and isinstance(override, Mapping):
            apps[app_id] = {**base_payload, **override}
        else:
            apps[app_id] = override
    merged["applications"] = apps
    return merged


def build_dev_inventory(compose: Compose, spec: DevInventorySpec) -> None:
    """Build the inventory folder described by `spec` and ensure its
    vault password file exists. Two side-effects, no return value: after
    this call, `spec.inventory_dir` contains a complete, variant-resolved
    inventory.
    """
    inv_root = spec.inventory_root()

    variant_payloads = _resolve_variant_payloads(
        roles_dir=str(compose.repo_root / "roles"),
        include=spec.include,
        active_variants=spec.variant_selectors(),
    )
    vars_payload = _bake_overrides(
        base_overrides=spec.overrides(),
        variant_payloads=variant_payloads,
    )

    cmd = [
        "infinito",
        "create",
        "inventory",
        inv_root,
        "--host",
        "localhost",
        "--ssl-disabled",
        "--vars-file",
        DEV_INVENTORY_VARS_FILE,
        "--vars",
        json.dumps(vars_payload, sort_keys=True),
        "--include",
        ",".join(spec.include),
    ]

    if should_use_mirrors_on_ci():
        mirrors_file = generate_ci_mirrors_file(compose, inventory_dir=inv_root)
        cmd += ["--mirror", mirrors_file]

    extra_env: dict[str, str] = {}
    if spec.services_disabled:
        extra_env["SERVICES_DISABLED"] = spec.services_disabled

    compose.exec(
        cmd,
        check=True,
        workdir="/opt/src/infinito",
        extra_env=extra_env or None,
    )
    _ensure_vault_password_file(compose, inventory_dir=inv_root)


PlanEntry = tuple[int, str, dict[str, int], tuple[str, ...]]


def filter_plan_to_variant(
    plan: list[PlanEntry],
    variant: int | None,
) -> list[PlanEntry]:
    """Pin a matrix plan to a single round when `variant` is set.

    `variant=None` returns the plan unchanged (full-matrix mode). An
    explicit variant index is matched against the plan's round indices;
    if it's out of range, raises `ValueError` so callers can surface a
    clean operator-facing error rather than silently doing nothing.
    """
    if variant is None:
        return plan
    for entry in plan:
        if entry[0] == variant:
            return [entry]
    available = sorted(entry[0] for entry in plan)
    raise ValueError(f"variant {variant} out of range; available rounds: {available}")


def plan_dev_inventory_matrix(
    *,
    roles_dir: str,
    primary_apps: Sequence[str],
    base_inventory_dir: str,
) -> list[PlanEntry]:
    """Return ``[(round_index, inventory_dir, round_variants, include), ...]``.

    `total_rounds = max(variant_count)` across the **primary** apps the
    user named. In each round R, every primary uses variant R clamped
    to its own count; transitive deps discovered for that round use R
    clamped to their own count too. The variant-aware resolver is
    invoked per round so the include set reflects the variant-merged
    topology — apps a variant pulls in via `services.<X>.enabled: true`
    appear in the include for that round (and not for rounds where
    they are not pulled).

    Inventory paths are suffixed with `-<round>` only when
    `total_rounds > 1`, so single-variant deploys keep the historical
    unsuffixed path.

    Pure function — only reads `meta/services.yml` / `meta/variants.yml`
    via the cached YAML helpers; writes nothing.
    """
    if not primary_apps:
        raise ValueError("plan_dev_inventory_matrix: primary_apps must not be empty")
    variants_per_app = get_variants(roles_dir=roles_dir)
    primary_variant_counts = {
        app_id: max(1, len(variants_per_app.get(app_id) or [{}]))
        for app_id in primary_apps
    }
    total_rounds = max(primary_variant_counts.values(), default=1)
    base = str(base_inventory_dir).rstrip("/")

    plan: list[PlanEntry] = []
    for round_index in range(total_rounds):
        primary_round_variants = {
            app_id: round_index if round_index < count else 0
            for app_id, count in primary_variant_counts.items()
        }
        services_overrides = _build_services_overrides_for_round(
            roles_dir=roles_dir,
            round_index=round_index,
            primary_app_variants=primary_round_variants,
        )
        include_R = _resolve_round_include(
            primary_apps=primary_apps,
            services_overrides=services_overrides,
        )
        # Extend round_variants with discovered deps' variants so deploy.py
        # and the inventory baker decide variant-cleanly per dep too.
        round_variants = dict(primary_round_variants)
        for dep in include_R:
            if dep in round_variants:
                continue
            dep_variants = variants_per_app.get(dep) or [{}]
            dep_count = max(1, len(dep_variants))
            round_variants[dep] = round_index if round_index < dep_count else 0

        inv_dir = f"{base}-{round_index}" if total_rounds > 1 else base
        plan.append((round_index, inv_dir, round_variants, include_R))
    return plan


def build_dev_inventory_matrix(
    compose: Compose,
    *,
    base_inventory_dir: str,
    primary_apps: Sequence[str],
    storage_constrained: bool,
    runtime: str,
    extra_vars: Mapping[str, Any] | None = None,
    services_disabled: str = "",
    include_filter: Sequence[str] | None = None,
) -> list[PlanEntry]:
    """Build every folder in the matrix plan and return the plan.

    `include_filter`, when provided, is the set of role names a caller
    has already filtered (e.g. by SERVICES_DISABLED removal of provider
    roles). Each round's include is intersected with this set before
    being baked, so the inventory and `--include` flag stay aligned
    with whatever the deploy step will actually deploy.
    """
    plan = plan_dev_inventory_matrix(
        roles_dir=str(compose.repo_root / "roles"),
        primary_apps=primary_apps,
        base_inventory_dir=base_inventory_dir,
    )
    allow: set[str] | None = set(include_filter) if include_filter is not None else None
    for _round_index, inv_dir, round_variants, include_R in plan:
        if allow is not None:
            include_R = tuple(role for role in include_R if role in allow)
        spec = DevInventorySpec(
            inventory_dir=inv_dir,
            include=include_R,
            storage_constrained=storage_constrained,
            runtime=runtime,
            extra_vars=extra_vars,
            services_disabled=services_disabled,
            active_variants=round_variants,
        )
        build_dev_inventory(compose, spec)
    return plan


def _ensure_vault_password_file(compose: Compose, *, inventory_dir: str) -> None:
    inv_root = str(inventory_dir).rstrip("/")
    pw_file = f"{inv_root}/.password"
    compose.exec(
        [
            "sh",
            "-lc",
            f"mkdir -p {inv_root} && "
            f"[ -f {pw_file} ] || "
            f"printf '%s\n' 'ci-vault-password' > {pw_file}",
        ],
        check=True,
    )
