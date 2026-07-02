"""Swarm variant-matrix round orchestrator.

Mirrors the compose matrix deploy (``cli.administration.deploy.development.deploy``)
for the swarm test cluster: for each variant round of the primary app it
provisions a per-round inventory (baking that round's ``meta/variants.yml``
overlay into ``host_vars`` so the deploy sees the round's config, e.g. the
keycloak totp-off variant), extends it with the swarm topology, writes runtime
extras, deploys via ``cli.administration.deploy.swarm`` (the Playwright e2e runs
in-deploy), waits for convergence + reachability, and purges the prior round's
stacks between rounds.

Runs on the cluster host (the test-deploy-swarm workflow's single orchestrator
step) and reaches the nodes through the existing ``scripts/tests/deploy/swarm``
helpers, which it drives per round via environment variables.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from . import PROJECT_ROOT

_SWARM_SCRIPTS = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "swarm"
_ROLES_DIR = str(PROJECT_ROOT / "roles")
_SWARM_EXTRAS_VARS = "inventories/development/swarm.yml"
_DEFAULT_INVENTORY_DIR = "/tmp/inv"  # noqa: S108 - ephemeral swarm-test inventory base in CI


def _run(cmd: list[str], *, env: dict[str, str], label: str) -> int:
    print(f"=== swarm-matrix: {label} ===", flush=True)
    return int(
        subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env, check=False).returncode
    )


def _provision(
    *, app_id: str, inv_dir: str, round_variants: dict[str, int], vars_payload: dict
) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    env["INFINITO_INVENTORY_DIR"] = inv_dir
    env["INFINITO_APP_VARIANTS"] = json.dumps(round_variants, sort_keys=True)
    env["INFINITO_VARS_PAYLOAD"] = json.dumps(vars_payload, sort_keys=True)
    return _run(
        ["bash", str(_SWARM_SCRIPTS / "05_provision_inventory.sh")],
        env=env,
        label=f"provision inventory ({inv_dir})",
    )


def _extend_inventory(*, app_id: str, inv_dir: str) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    env["INV_PATH"] = f"{inv_dir}/devices.yml"
    return _run(
        ["python3", "-m", "utils.tests.swarm.extend_inventory"],
        env=env,
        label="extend inventory (workers + group memberships)",
    )


def _force_shared_db(*, inv_dir: str) -> int:
    env = os.environ.copy()
    env["INV_DIR"] = inv_dir
    return _run(
        ["python3", "-m", "utils.tests.swarm.force_shared_db"],
        env=env,
        label="force shared DB (swarm: embedded DB is compose-only)",
    )


def _write_extras(*, extras_path: str) -> int:
    env = os.environ.copy()
    env["OUT_PATH"] = extras_path
    return _run(
        ["python3", "-m", "utils.tests.swarm.write_extras"],
        env=env,
        label=f"write runtime extras ({extras_path})",
    )


def _deploy(
    *, app_id: str, inv_dir: str, extras_path: str, round_index: int, total: int
) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    cmd = [
        "python3",
        "-m",
        "cli.administration.deploy.swarm",
        f"{inv_dir}/devices.yml",
        "-p",
        f"{inv_dir}/.password",
        "--skip-build",
        "--skip-cleanup",
        "--skip-backup",
        "-e",
        f"@{_SWARM_EXTRAS_VARS}",
        "-e",
        f"@{extras_path}",
        "-e",
        f"VARIANT_INDEX={json.dumps(round_index)}",
    ]
    return _run(env=env, cmd=cmd, label=f"deploy round {round_index + 1}/{total}")


def _converge_and_verify(*, app_id: str) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    rc = _run(
        ["bash", str(_SWARM_SCRIPTS / "07_wait_converge.sh")],
        env=env,
        label="wait for stack convergence",
    )
    if rc != 0:
        return rc
    return _run(
        ["bash", str(_SWARM_SCRIPTS / "08_verify_reachable.sh")],
        env=env,
        label="verify reachability",
    )


def _purge(*, purge_set: tuple[str, ...]) -> int:
    if not purge_set:
        return 0
    env = os.environ.copy()
    env["apps"] = ",".join(purge_set)
    return _run(
        ["bash", str(_SWARM_SCRIPTS / "purge_stacks.sh")],
        env=env,
        label=f"purge prior-round stacks ({', '.join(purge_set)})",
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    from cli.administration.deploy.development.variant_select import add_variant_args

    p = argparse.ArgumentParser(
        prog="cli.administration.deploy.swarm.matrix",
        description=(
            "Iterate the variant-matrix rounds of one application against the "
            "live swarm test cluster."
        ),
    )
    p.add_argument(
        "--id",
        "--app",
        dest="app",
        default=os.environ.get("APP_ID"),
        help="Primary application id (default: $APP_ID).",
    )
    p.add_argument(
        "--inventory-dir",
        default=os.environ.get(
            "INFINITO_INVENTORY_DIR", _DEFAULT_INVENTORY_DIR
        ),  # nocheck: swarm-test base; matrix sets it per round, compose resolves the key via its own handler
        help=(
            "Base inventory dir; the planner derives per-round folders "
            "<dir>-<n> (default: $INFINITO_INVENTORY_DIR or /tmp/inv)."
        ),
    )
    add_variant_args(p, action="deploy")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    app_id = (args.app or "").strip()
    if not app_id:
        raise SystemExit("swarm-matrix: no application id (set $APP_ID or pass --id)")

    from cli.administration.deploy.development.inventory import (
        _bake_overrides,
        _resolve_variant_payloads,
        plan_dev_inventory_matrix,
    )
    from cli.administration.deploy.development.variant_select import (
        apply_variant_filter,
    )

    plan = plan_dev_inventory_matrix(
        roles_dir=_ROLES_DIR,
        primary_apps=[app_id],
        base_inventory_dir=str(args.inventory_dir),
    )
    try:
        plan = apply_variant_filter(plan, args)
    except ValueError as exc:
        raise SystemExit(f"--variant: {exc}") from exc

    total = len(plan)
    rc = 0
    for plan_index, (
        round_index,
        inv_dir,
        round_variants,
        round_include,
        round_purge_set,
    ) in enumerate(plan):
        inv_root = inv_dir.rstrip("/")

        if plan_index > 0:
            rc = _purge(purge_set=round_purge_set)
            if rc != 0:
                return rc

        variant_payloads = _resolve_variant_payloads(
            roles_dir=_ROLES_DIR,
            include=round_include,
            active_variants=round_variants,
        )
        vars_payload = _bake_overrides(
            base_overrides={}, variant_payloads=variant_payloads
        )
        extras_path = f"{inv_root}/swarm-nfs-extras.yml"

        rc = _provision(
            app_id=app_id,
            inv_dir=inv_root,
            round_variants=round_variants,
            vars_payload=vars_payload,
        )
        if rc == 0:
            rc = _force_shared_db(inv_dir=inv_root)
        if rc == 0:
            rc = _extend_inventory(app_id=app_id, inv_dir=inv_root)
        if rc == 0:
            rc = _write_extras(extras_path=extras_path)
        if rc == 0:
            rc = _deploy(
                app_id=app_id,
                inv_dir=inv_root,
                extras_path=extras_path,
                round_index=round_index,
                total=total,
            )
        if rc == 0:
            rc = _converge_and_verify(app_id=app_id)
        if rc != 0:
            return rc

    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
