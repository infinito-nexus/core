"""Argument parsing and round orchestration for the ``deploy`` subcommand."""

from __future__ import annotations

import argparse
import os

from cli.administration.deploy.development.common import (
    make_compose,
    resolve_container,
)
from cli.administration.deploy.development.inventory import plan_dev_inventory_matrix
from cli.administration.deploy.development.variant_select import (
    add_variant_args,
    apply_variant_filter,
)
from cli.administration.inventory.provision.services_disabler import (
    find_provider_roles,
    parse_services_disabled,
)

from .drill import _maybe_recover_drill
from .purge import _purge_app_entities
from .run import _run_deploy


def _env_full_cycle() -> bool:
    return os.environ.get("full_cycle", "").strip().lower() == "true"


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "deploy", help="Run deploy inside the infinito container (requires inventory)."
    )
    p.add_argument(
        "--inventory-dir",
        default=os.environ.get("INFINITO_INVENTORY_DIR"),
        required=os.environ.get("INFINITO_INVENTORY_DIR") is None,
        help=(
            "Inventory directory base (default: $INFINITO_INVENTORY_DIR). When the "
            "primary apps declare more than one matrix-deploy variant, the "
            "wrapper iterates the sibling folders `<dir>-0`, `<dir>-1`, ... "
            "produced by the matching `init` step; otherwise the directory "
            "is used as-is."
        ),
    )

    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--apps",
        help="One or more application ids (will include run_after deps automatically).",
    )
    g.add_argument(
        "--id",
        nargs="+",
        default=None,
        help="Explicit application ids (space-separated).",
    )
    p.add_argument(
        "--debug",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable/disable Ansible debug mode (default: disabled).",
    )
    add_variant_args(p, action="deploy")
    p.add_argument(
        "--full-cycle",
        action=argparse.BooleanOptionalAction,
        default=_env_full_cycle(),
        help=(
            "After each round's regular deploy, immediately re-run the "
            "deploy with `-e ASYNC_ENABLED=true` (the async update pass). "
            "Pass 1 + Pass 2 stay co-located on the SAME variant so the "
            "async re-deploy always runs against the host state the "
            "matching sync deploy just produced. Defaults to the "
            "full_cycle environment variable (true|false) when set."
        ),
    )
    p.add_argument(
        "ansible_args",
        nargs=argparse.REMAINDER,
        help="Passthrough args appended to `cli.administration.deploy.dedicated` (use `--` to separate).",
    )
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    compose = make_compose()

    if args.apps:
        primary_app_ids = [
            a.strip() for a in args.apps.replace(",", " ").split() if a.strip()
        ]
    else:
        primary_app_ids = list(args.id or [])

    raw_disabled = os.environ.get("disable", "").strip()
    disabled_app_ids: set[str] = set()
    if raw_disabled:
        services = parse_services_disabled(raw_disabled)
        roles_dir = compose.repo_root / "roles"
        provider_map = find_provider_roles(services, roles_dir)
        disabled_app_ids = set(provider_map.values())
        primary_app_ids = [
            app_id for app_id in primary_app_ids if app_id not in disabled_app_ids
        ]

    if not primary_app_ids:
        raise SystemExit("All primary apps disabled by `disable`: nothing to deploy")

    passthrough = list(args.ansible_args or [])
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]

    plan = plan_dev_inventory_matrix(
        roles_dir=str(compose.repo_root / "roles"),
        primary_apps=primary_app_ids,
        base_inventory_dir=str(args.inventory_dir),
    )
    try:
        plan = apply_variant_filter(plan, args)
    except ValueError as exc:
        raise SystemExit(f"--variant: {exc}") from exc

    container_name = resolve_container()

    rc = 0
    for plan_index, (
        round_index,
        inv_dir,
        round_variants,
        include_roles,
        purge_roles,
    ) in enumerate(plan):
        round_deploy_ids = [
            role for role in include_roles if role not in disabled_app_ids
        ]

        if plan_index > 0:
            purge_targets = [
                role for role in purge_roles if role not in disabled_app_ids
            ]
            _purge_app_entities(container=container_name, app_ids=purge_targets)

        def run_pass(
            extra_vars: dict,
            *,
            deploy_ids: list[str] = round_deploy_ids,
            inventory_dir: str = inv_dir,
        ) -> int:
            return _run_deploy(
                compose,
                deploy_ids=deploy_ids,
                debug=bool(args.debug),
                passthrough=passthrough,
                inventory_dir=inventory_dir,
                container_name=container_name,
                extra_ansible_vars=extra_vars,
            )

        pass_label = (
            f"matrix-deploy: round {round_index + 1}/{len(plan)} "
            f"inv={inv_dir} variants={round_variants} apps={round_deploy_ids}"
        )
        print(f"=== {pass_label} PASS 1 (sync) ===")
        rc = run_pass({"VARIANT_INDEX": round_index})
        if rc != 0:
            return rc

        if bool(args.full_cycle):
            _maybe_recover_drill(compose, plan_index)
            print(f"=== {pass_label} PASS 2 (async) ===")
            rc = run_pass({"ASYNC_ENABLED": True, "VARIANT_INDEX": round_index})
            if rc != 0:
                return rc

    return rc
