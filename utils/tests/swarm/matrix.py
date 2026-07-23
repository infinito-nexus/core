"""Swarm variant-matrix round orchestrator.

Mirrors the compose matrix deploy (``cli.administration.deploy.development.deploy``)
for the swarm test cluster: for each variant round of the primary app it
provisions a per-round inventory (baking that round's ``meta/variants.yml``
overlay into ``host_vars`` so the deploy sees the round's config, e.g. the
keycloak totp-off variant), extends it with the swarm topology, writes runtime
extras, and deploys via ``cli.administration.deploy.swarm`` (the Playwright e2e
runs in-deploy). Each round mirrors the compose ``--full-cycle``: an initial
deploy then an async update pass, each followed by a convergence + reachability
wait; on the first round the backup + restore DR drill runs between them. Prior
rounds' stacks are purged between rounds.

Runs on the cluster host (the test-deploy-swarm workflow's single orchestrator
step) and reaches the nodes through the existing ``scripts/tests/deploy/swarm``
helpers, which it drives per round via environment variables.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

from utils import PROJECT_ROOT

_SWARM_DIR = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "swarm"
_SWARM_SCRIPTS = _SWARM_DIR / "routine"
_ROLES_DIR = str(PROJECT_ROOT / "roles")
_SWARM_EXTRAS_VARS = "inventories/development/swarm.yml"
_DEFAULT_INVENTORY_DIR = "/tmp/inv"  # noqa: S108 - ephemeral swarm-test inventory base in CI


def _run(cmd: list[str], *, env: dict[str, str], label: str) -> int:
    """Run a matrix step, aborting visibly before the runner disk fills.

    The Actions Worker dies silently on ENOSPC while writing its own logs, so
    a full disk truncates the job without diagnostics; terminating the step at
    <6G free keeps enough room for rescue artifacts and the log upload.
    """
    print(f"=== swarm-matrix: {label} ===", flush=True)
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env)
    while True:
        try:
            return int(proc.wait(timeout=30))
        except subprocess.TimeoutExpired:
            if shutil.disk_usage("/").free < 6 * 2**30:
                print(
                    "=== swarm-matrix: DISK EXHAUSTION IMMINENT "
                    "(<6G free on /) - aborting step ===",
                    flush=True,
                )
                subprocess.run(["df", "-h", "/"], check=False)
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                return 75


def _provision(
    *, app_id: str, inv_dir: str, round_variants: dict[str, int], vars_payload: dict
) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    env["INFINITO_INVENTORY_DIR"] = inv_dir
    env["INFINITO_APP_VARIANTS"] = json.dumps(round_variants, sort_keys=True)
    env["INFINITO_VARS_PAYLOAD"] = json.dumps(vars_payload, sort_keys=True)
    return _run(
        ["bash", str(_SWARM_SCRIPTS / "02_provision_inventory.sh")],
        env=env,
        label=f"provision inventory ({inv_dir})",
    )


def _extend_inventory(
    *, app_id: str, inv_dir: str, round_variants: dict[str, int]
) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    env["INV_PATH"] = f"{inv_dir}/devices.yml"
    env["INFINITO_APP_VARIANTS"] = json.dumps(round_variants, sort_keys=True)
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
        ["python3", "-m", "utils.tests.swarm.write.extras"],
        env=env,
        label=f"write runtime extras ({extras_path})",
    )


def _deploy(
    *,
    app_id: str,
    inv_dir: str,
    extras_path: str,
    round_index: int,
    total: int,
    update_pass: bool = False,
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
    pass_label = (
        f"matrix-deploy: round {round_index + 1}/{total} "
        f"variants=[{round_index}] apps=['{app_id}']"
    )
    if update_pass:
        cmd += ["-e", "ASYNC_ENABLED=true"]
        label = f"update pass (round {round_index + 1}/{total})"
        print(f"=== {pass_label} PASS 2 (async) ===", flush=True)
    else:
        label = f"deploy round {round_index + 1}/{total}"
        print(f"=== {pass_label} PASS 1 (sync) ===", flush=True)
    return _run(env=env, cmd=cmd, label=label)


def _deploy_backup_host(*, app_id: str, inv_dir: str, extras_path: str) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    cmd = [
        "python3",
        "-m",
        "cli.administration.deploy.dedicated",
        f"{inv_dir}/backup.yml",
        "-p",
        f"{inv_dir}/.password",
        "--skip-build",
        "--skip-cleanup",
        "--skip-backup",
        "-e",
        f"@{_SWARM_EXTRAS_VARS}",
        "-e",
        f"@{extras_path}",
    ]
    return _run(env=env, cmd=cmd, label="deploy backup host (backup.yml)")


def _converge_and_verify(*, app_id: str) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    rc = _run(
        ["bash", str(_SWARM_SCRIPTS / "03_wait_converge.sh")],
        env=env,
        label="wait for stack convergence",
    )
    if rc != 0:
        return rc
    return _run(
        ["bash", str(_SWARM_SCRIPTS / "04_verify_reachable.sh")],
        env=env,
        label="verify reachability",
    )


def _backup_restore_drill(*, app_id: str, inv_dir: str, extras_path: str) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    env["INFINITO_INVENTORY_DIR"] = inv_dir
    env["DRILL_EXTRAS"] = extras_path
    return _run(
        ["bash", str(_SWARM_SCRIPTS / "backup" / "base.sh")],
        env=env,
        label="backup + restore DR drill",
    )


def _verify_recovered_marker(*, app_id: str) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    return _run(
        ["bash", str(_SWARM_SCRIPTS / "backup" / "verify_recovered_marker.sh")],
        env=env,
        label="verify recovered marker (post update pass)",
    )


def _purge(*, purge_set: tuple[str, ...]) -> int:
    if not purge_set:
        return 0
    env = os.environ.copy()
    env["apps"] = ",".join(purge_set)
    return _run(
        ["bash", str(_SWARM_DIR / "utils" / "clean" / "purge_stacks.sh")],
        env=env,
        label=f"purge prior-round stacks ({', '.join(purge_set)})",
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    from cli.administration.deploy.development.variant_select import add_variant_args

    p = argparse.ArgumentParser(
        prog="utils.tests.swarm.matrix",
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
        from utils.tests.swarm.write.extras import backup_applications_overrides

        vars_payload = _bake_overrides(
            base_overrides={
                "applications": backup_applications_overrides(
                    os.environ["MGR_IP"], os.environ["NFS_IP"]
                )
            },
            variant_payloads=variant_payloads,
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
            rc = _extend_inventory(
                app_id=app_id, inv_dir=inv_root, round_variants=round_variants
            )
        if rc == 0:
            rc = _write_extras(extras_path=extras_path)
        if rc == 0:
            rc = _deploy(
                app_id=app_id,
                inv_dir=inv_root,
                extras_path=f"{inv_root}/swarm-nfs-extras.deploy.yml",
                round_index=round_index,
                total=total,
            )
        if rc == 0:
            rc = _converge_and_verify(app_id=app_id)
        if rc == 0 and round_index == 0:
            rc = _deploy_backup_host(
                app_id=app_id,
                inv_dir=inv_root,
                extras_path=f"{inv_root}/swarm-nfs-extras.deploy.yml",
            )
        if rc == 0 and round_index == 0:
            rc = _backup_restore_drill(
                app_id=app_id, inv_dir=inv_root, extras_path=extras_path
            )
        if rc == 0:
            rc = _deploy(
                app_id=app_id,
                inv_dir=inv_root,
                extras_path=f"{inv_root}/swarm-nfs-extras.deploy.yml",
                round_index=round_index,
                total=total,
                update_pass=True,
            )
        if rc == 0:
            rc = _converge_and_verify(app_id=app_id)
        if rc == 0 and round_index == 0:
            rc = _verify_recovered_marker(app_id=app_id)
        if rc != 0:
            return rc

    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
