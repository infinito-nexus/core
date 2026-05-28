"""Inventory folder materialisation.

`build_dev_inventory` is the SPOT that turns a `DevInventorySpec` into a
fully baked inventory folder via the `infinito administration inventory
provision` CLI. `build_dev_inventory_matrix` is the orchestrator: it
runs the planner and builds every round's folder.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from cli.administration.deploy.development.common import DEV_INVENTORY_VARS_FILE
from cli.administration.deploy.development.mirrors import (
    generate_ci_mirrors_file,
    should_use_mirrors_on_ci,
)

from .payload import _bake_overrides, _resolve_variant_payloads
from .planner import plan_dev_inventory_matrix
from .spec import DevInventorySpec, PlanEntry

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from cli.administration.deploy.development.compose import Compose


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
        "administration",
        "inventory",
        "provision",
        inv_root,
        "--host",
        "localhost",
        "--vars-file",
        DEV_INVENTORY_VARS_FILE,
        "--vars",
        json.dumps(vars_payload, sort_keys=True),
        "--include",
        ",".join(spec.include),
    ]

    variant_selectors = spec.variant_selectors()
    if variant_selectors:
        cmd += ["--app-variants", json.dumps(variant_selectors, sort_keys=True)]

    if should_use_mirrors_on_ci():
        mirrors_file = generate_ci_mirrors_file(compose, inventory_dir=inv_root)
        cmd += ["--mirror", mirrors_file]

    extra_env: dict[str, str] = {}
    if spec.services_disabled:
        extra_env["disable"] = spec.services_disabled

    compose.exec(
        cmd,
        check=True,
        workdir=os.environ["INFINITO_SRC_DIR"],
        extra_env=extra_env or None,
    )
    _ensure_vault_password_file(compose, inventory_dir=inv_root)


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
    has already filtered (e.g. by `disable` removal of provider
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
    for _round_index, inv_dir, round_variants, raw_include, _purge_set in plan:
        round_include = (
            tuple(role for role in raw_include if role in allow)
            if allow is not None
            else raw_include
        )
        spec = DevInventorySpec(
            inventory_dir=inv_dir,
            include=round_include,
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
