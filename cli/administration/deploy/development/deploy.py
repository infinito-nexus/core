from __future__ import annotations

import argparse
import json
import os
import subprocess
from typing import TYPE_CHECKING, Any

from cli.administration.inventory.provision.services_disabler import (
    find_provider_roles,
    parse_services_disabled,
)

from . import PROJECT_ROOT
from .common import (
    make_compose,
    resolve_container,
)
from .inventory import filter_plan_to_variant, plan_dev_inventory_matrix

if TYPE_CHECKING:
    from collections.abc import Mapping


def _env_variant() -> int | None:
    raw = os.environ.get("variant", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(
            f"variant environment variable must be an integer, got {raw!r}"
        ) from None


def _env_full_cycle() -> bool:
    return os.environ.get("full_cycle", "").strip().lower() == "true"


def _run_deploy(
    compose,
    *,
    deploy_ids: list[str],
    debug: bool,
    passthrough: list[str],
    inventory_dir: str,
    container_name: str,
    extra_ansible_vars: Mapping[str, Any] | None = None,
) -> int:
    inv_root = str(inventory_dir).rstrip("/")
    inv_file = f"{inv_root}/devices.yml"
    pw_file = f"{inv_root}/.password"

    cmd = [
        "python3",
        "-m",
        "cli.administration.deploy.dedicated",
        inv_file,
        "-p",
        pw_file,
        "-vv",
        "--assert",
        "true",
        "--diff",
        "--id",
        *deploy_ids,
    ]
    if debug:
        cmd.insert(cmd.index("--diff") + 1, "--debug")

    # Ansible extra-vars (`-e key=value`) for caller-supplied runtime toggles
    # (typically the async-pass override). JSON-encoding the value preserves
    # bool/int/list semantics across the shell hop into Ansible.
    if extra_ansible_vars:
        for key, value in extra_ansible_vars.items():
            cmd.extend(["-e", f"{key}={json.dumps(value)}"])

    if passthrough:
        cmd.extend(passthrough)

    extra_env: dict[str, str] = {
        # Force ANSI colors even when no TTY is allocated (CI default).
        "ANSIBLE_FORCE_COLOR": "1",
        "PY_COLORS": "1",
        "TERM": "xterm-256color",
    }
    services_disabled = os.environ.get("disable", "")
    if services_disabled:
        extra_env["disable"] = services_disabled

    ansible_log_path = (
        os.environ.get("ANSIBLE_LOG_PATH") or "/tmp/infinito-deploy.log"  # noqa: S108
    )
    extra_env["ANSIBLE_LOG_PATH"] = ansible_log_path

    for key in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GITHUB_REPOSITORY_OWNER",
        "GITHUB_REPOSITORY",
    ):
        val = os.environ.get(key)
        if val:
            extra_env[key] = val

    # The Playwright E2E gate now keys on `RUNTIME` from the inventory's
    # host_vars (baked at init time by `cli.administration.deploy.development.init`).
    # We no longer need to forward GITHUB_ACTIONS / ACT /
    # INFINITO_MAKE_DEPLOY / INFINITO_SKIP_E2E into the container at deploy
    # time: by then the runtime decision is already serialised into the
    # inventory the deploy stage consumes.

    r = compose.exec(
        cmd,
        check=False,
        live=True,
        extra_env=extra_env,
    )

    return int(r.returncode)


def _purge_app_entities(*, container: str, app_ids: list[str]) -> None:
    """Run the per-app cleanup script for every app from the previous
    matrix-deploy round before the next round starts.

    `scripts/tests/deploy/local/purge/entity.sh` removes the
    application's containers, networks, and Ansible-managed state on
    the host so the next round boots from a clean slate. Failures are
    surfaced (the matrix MUST NOT silently mix variant state across
    rounds).
    """
    if not app_ids:
        return
    repo_root = PROJECT_ROOT
    purge_script = (
        repo_root / "scripts" / "tests" / "deploy" / "local" / "purge" / "entity.sh"
    )
    env = os.environ.copy()
    env["apps"] = ",".join(app_ids)
    env["INFINITO_CONTAINER"] = container
    print(
        "=== matrix-deploy: purging entities between rounds for "
        f"{', '.join(app_ids)} ==="
    )
    subprocess.run(
        ["bash", str(purge_script)],
        cwd=str(repo_root),
        env=env,
        check=True,
    )


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
    p.add_argument(
        "--variant",
        type=int,
        default=_env_variant(),
        help=(
            "Pin the matrix deploy to a single round (zero-based index), "
            "skipping inter-round cleanup. Useful for redeploying one "
            "specific variant without iterating the whole matrix. Defaults "
            "to the variant environment variable when set, otherwise "
            "full-matrix mode."
        ),
    )
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

    # Remove any app IDs that were disabled via `disable` so the
    # deploy list stays consistent with the inventory created by init.
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
        raise SystemExit("All primary apps disabled by `disable` — nothing to deploy")

    # argparse.REMAINDER includes the leading '--' if present; drop it
    passthrough = list(args.ansible_args or [])
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]

    # Matrix-deploy: the init step produced one inventory folder per round
    # (`<dir>-0`, `<dir>-1`, ...; or just `<dir>` when there is a single
    # round) with the per-app variant data already baked into each folder's
    # `host_vars`. Here we just iterate the same plan and deploy against
    # each folder. Between rounds we purge the previous round's full
    # include set so round R starts from a clean host; every round then
    # redeploys its own full include. The final round is followed by no
    # purge so the last state remains available for inspection /
    # follow-up specs.
    #
    # Matrix planning is variant-aware (see inventory.py): for each round
    # the planner consults the variant-merged services map of every
    # primary app and pulls in transitive deps that ROUND wants. This
    # is the single SPOT for "what is in this round's deploy" — both
    # init and deploy walk the same plan so they cannot drift.
    plan = plan_dev_inventory_matrix(
        roles_dir=str(compose.repo_root / "roles"),
        primary_apps=primary_app_ids,
        base_inventory_dir=str(args.inventory_dir),
    )
    try:
        plan = filter_plan_to_variant(plan, args.variant)
    except ValueError as exc:
        raise SystemExit(f"--variant: {exc}") from exc

    # INFINITO_CONTAINER is the single SPOT — defaults.sh keeps it in
    # lock-step with INFINITO_DISTRO across matrix iterations. Read it
    # strictly here; no fallback derivation, no env-vs-arg ambiguity.
    container_name = resolve_container()

    rc = 0
    for plan_index, (
        round_index,
        inv_dir,
        round_variants,
        include_R,
        purge_set_R,
    ) in enumerate(plan):
        round_include = [role for role in include_R if role not in disabled_app_ids]
        round_deploy_ids = round_include

        # WHY purge_set (= union across all rounds) and not previous_round_include: a variant pinning `services.<X>.shared: false` would otherwise leak its bundled provider into the next round's host.
        if plan_index > 0:
            purge_targets = [
                role for role in purge_set_R if role not in disabled_app_ids
            ]
            _purge_app_entities(container=container_name, app_ids=purge_targets)

        pass_label = (
            f"matrix-deploy: round {round_index + 1}/{len(plan)} "
            f"inv={inv_dir} variants={round_variants} apps={round_deploy_ids}"
        )
        # `VARIANT_INDEX` (0-based round id) is pushed as an Ansible extra
        # var so consumers like the test-e2e-playwright role can namespace
        # their per-run artifacts by variant + pass and avoid overwriting
        # earlier rounds' reports.
        print(f"=== {pass_label} PASS 1 (sync) ===")
        rc = _run_deploy(
            compose,
            deploy_ids=round_deploy_ids,
            debug=bool(args.debug),
            passthrough=passthrough,
            inventory_dir=inv_dir,
            container_name=container_name,
            extra_ansible_vars={"VARIANT_INDEX": round_index},
        )
        if rc != 0:
            return rc

        # When `--full-cycle` is set, the async update pass runs IMMEDIATELY
        # against the same variant's host state, before we move to the next
        # round. This co-locates PASS 1 and PASS 2 per variant so the async
        # re-deploy never accidentally targets a host that was left in a
        # different variant by a prior round.
        if bool(args.full_cycle):
            print(f"=== {pass_label} PASS 2 (async) ===")
            rc = _run_deploy(
                compose,
                deploy_ids=round_deploy_ids,
                debug=bool(args.debug),
                passthrough=passthrough,
                inventory_dir=inv_dir,
                container_name=container_name,
                extra_ansible_vars={
                    "ASYNC_ENABLED": True,
                    "VARIANT_INDEX": round_index,
                },
            )
            if rc != 0:
                return rc

    return rc
