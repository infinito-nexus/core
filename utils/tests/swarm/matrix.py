"""Swarm variant-matrix round orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from utils import PROJECT_ROOT
from utils.storage.constrained import host_storage_constrained
from utils.tests.swarm.derive_includes import derive_includes, variant_scope
from utils.tests.swarm.extend_inventory import mesh_enabled
from utils.tests.swarm.mesh import (
    bootstrap_mesh,
    converge_mesh,
    lab_sudo_without_prompt,
    mesh_controller,
    switch_to_mesh_transport,
    transport_bench,
    write_mesh,
)
from utils.tests.swarm.run import DISK_FLOOR_MB, run_step
from utils.tests.swarm.write.extras import ensure_swarm_keypairs

_SWARM_DIR = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "swarm"
_SWARM_SCRIPTS = _SWARM_DIR / "routine"
_ROLES_DIR = str(PROJECT_ROOT / "roles")
_SWARM_EXTRAS_VARS = "inventories/development/swarm.yml"
_DEFAULT_INVENTORY_DIR = "/tmp/inv"  # noqa: S108 - ephemeral swarm-test inventory base in CI


def _provision(
    *, app_id: str, inv_dir: str, round_variants: dict[str, int], vars_payload: dict
) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    env["INFINITO_INVENTORY_DIR"] = inv_dir
    env["INFINITO_APP_VARIANTS"] = json.dumps(round_variants, sort_keys=True)
    env["INFINITO_VARS_PAYLOAD"] = json.dumps(vars_payload, sort_keys=True)
    return run_step(
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
    return run_step(
        ["python3", "-m", "utils.tests.swarm.extend_inventory"],
        env=env,
        label="extend inventory (workers + group memberships)",
    )


def _force_shared_db(*, inv_dir: str) -> int:
    env = os.environ.copy()
    env["INV_DIR"] = inv_dir
    return run_step(
        ["python3", "-m", "utils.tests.swarm.force_shared_db"],
        env=env,
        label="force shared DB (swarm: embedded DB is compose-only)",
    )


def _write_extras(*, extras_path: str) -> int:
    env = os.environ.copy()
    env["OUT_PATH"] = extras_path
    return run_step(
        ["python3", "-m", "utils.tests.swarm.write.extras"],
        env=env,
        label=f"write runtime extras ({extras_path})",
    )


def _reset_credentials(
    *, app_id: str, inv_dir: str, round_variants: dict[str, int]
) -> int:
    """Regenerate the round's credentials so the update pass has to carry them."""
    return run_step(
        [
            "python3",
            "-m",
            "cli.administration.inventory.credentials.reset",
            "--inventory-dir",
            inv_dir,
            "--host",
            os.environ["MGR"],
            "--schema",
            "--users",
            "--include",
            *derive_includes(app_id, variants=round_variants),
            "--app-variants",
            json.dumps(round_variants, sort_keys=True),
            "--mirror",
            "--mirror-keep",
            "applications.svc-net-wireguard",
            "--backup",
            "--except",
            "administrator",
        ],
        env=os.environ.copy(),
        label="reset credentials (rotation gate before the async pass)",
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
    """Run one deploy of the round.

    Args:
        update_pass: run it as the async update pass.
    """
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
        "-e",
        f"PRIMARY_APPS={json.dumps([app_id])}",
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
    return run_step(env=env, cmd=cmd, label=label)


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
    return run_step(env=env, cmd=cmd, label="deploy backup host (backup.yml)")


def _converge_and_verify(*, app_id: str) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    rc = run_step(
        ["bash", str(_SWARM_SCRIPTS / "03_wait_converge.sh")],
        env=env,
        label="wait for stack convergence",
    )
    if rc != 0:
        return rc
    return run_step(
        ["bash", str(_SWARM_SCRIPTS / "04_verify_reachable.sh")],
        env=env,
        label="verify reachability",
    )


def _drill_env(*, app_id: str, inv_dir: str, extras_path: str) -> dict[str, str]:
    """The environment the drill reads, for a probe or for the real run."""
    env = os.environ.copy()
    env["APP_ID"] = app_id
    env["INFINITO_INVENTORY_DIR"] = inv_dir
    env["DRILL_EXTRAS"] = extras_path
    env["DISK_FLOOR_MB"] = str(DISK_FLOOR_MB)
    return env


def _drill_is_coming(*, app_id: str, inv_dir: str, extras_path: str) -> bool:
    """Whether the drill will tear this round's stack down and recover it."""
    env = _drill_env(app_id=app_id, inv_dir=inv_dir, extras_path=extras_path)
    env["DRILL_PROBE"] = "true"
    probe = subprocess.run(
        ["bash", str(_SWARM_SCRIPTS / "backup" / "base.sh")],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if "DRILL=no" in probe.stdout:
        return False
    if "DRILL=yes" not in probe.stdout:
        print(f"=== drill probe gave no verdict for {app_id}; assuming it drills ===")
    return True


def _backup_restore_drill(*, app_id: str, inv_dir: str, extras_path: str) -> int:
    return run_step(
        ["bash", str(_SWARM_SCRIPTS / "backup" / "base.sh")],
        env=_drill_env(app_id=app_id, inv_dir=inv_dir, extras_path=extras_path),
        label="backup + restore DR drill",
    )


def _backup_phase(
    *, app_id: str, inv_dir: str, deploy_extras: str, drill_extras: str
) -> int:
    """Bring the backup node up and drill backup, teardown and recovery."""
    rc = _deploy_backup_host(app_id=app_id, inv_dir=inv_dir, extras_path=deploy_extras)
    if rc == 0:
        rc = _backup_restore_drill(
            app_id=app_id, inv_dir=inv_dir, extras_path=drill_extras
        )
    return rc


def _verify_recovered_marker(*, app_id: str) -> int:
    env = os.environ.copy()
    env["APP_ID"] = app_id
    return run_step(
        ["bash", str(_SWARM_SCRIPTS / "backup" / "verify_recovered_marker.sh")],
        env=env,
        label="verify recovered marker (post update pass)",
    )


def _mesh_prologue(
    *,
    app_id: str,
    inv_dir: str,
    extras_path: str,
    round_variants: dict[str, int],
) -> int:
    """Put every node and the controller on the mesh, then move the transport.

    The credential reset runs here rather than between the passes, where the
    direct arm has it: its mirror copies the manager's host_vars over every
    other host, which after the switch would hand every worker the manager's
    mesh address.

    Args:
        app_id: primary application of the round.
        inv_dir: inventory directory of the round.
        extras_path: round extras, for the optional transport benchmark.
        round_variants: the round's ``{app_id: variant_index}`` map.
    """
    rc = bootstrap_mesh(inv_dir=inv_dir)
    if rc == 0:
        rc = lab_sudo_without_prompt(inv_dir=inv_dir)
    if rc == 0:
        rc = _reset_credentials(
            app_id=app_id, inv_dir=inv_dir, round_variants=round_variants
        )
    if rc == 0:
        rc = write_mesh(inv_dir=inv_dir, rotate=True)
    if rc == 0:
        rc = converge_mesh(inv_dir=inv_dir)
    if rc == 0:
        rc = mesh_controller(inv_dir=inv_dir)
    if rc == 0:
        rc = transport_bench(
            inv_dir=inv_dir, extras_path=extras_path, label="docker"
        )
    if rc == 0:
        rc = switch_to_mesh_transport(inv_dir=inv_dir)
    if rc == 0:
        rc = transport_bench(
            inv_dir=inv_dir, extras_path=extras_path, label="ssh over the mesh"
        )
    return rc


def _purge(*, purge_set: tuple[str, ...]) -> int:
    if not purge_set:
        return 0
    env = os.environ.copy()
    env["apps"] = ",".join(purge_set)
    return run_step(
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
    meshed = mesh_enabled()
    for plan_index, (
        round_index,
        inv_dir,
        round_variants,
        _round_include,
        round_purge_set,
    ) in enumerate(plan):
        inv_root = inv_dir.rstrip("/")

        if plan_index > 0:
            rc = _purge(purge_set=round_purge_set)
            if rc != 0:
                return rc

        variant_payloads = _resolve_variant_payloads(
            roles_dir=_ROLES_DIR,
            include=variant_scope(app_id, variants=round_variants),
            active_variants=round_variants,
        )
        from utils.tests.swarm.backup_repos import backup_provider_ips
        from utils.tests.swarm.write.extras import backup_applications_overrides

        providers = backup_provider_ips(
            app_id=app_id,
            variants=round_variants,
            manager=os.environ["MGR_IP"],
            nfs_server=os.environ["NFS_IP"],
        )
        print(
            f"=== swarm-matrix: remote-2-local backup providers "
            f"(round {round_index}): {', '.join(providers)} ===",
            flush=True,
        )
        pubkeys = ensure_swarm_keypairs()
        vars_payload = _bake_overrides(
            base_overrides={
                "applications": backup_applications_overrides(providers),
                "users": {
                    name: {"authorized_keys": [key]} for name, key in pubkeys.items()
                },
                "STORAGE_CONSTRAINED": host_storage_constrained(
                    [app_id], round_variants, local_vantage="/"
                ),
            },
            variant_payloads=variant_payloads,
        )
        extras_path = f"{inv_root}/swarm-nfs-extras.yml"
        deploy_extras = f"{inv_root}/swarm-nfs-extras.deploy.yml"

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
            rc = write_mesh(inv_dir=inv_root)
        if rc == 0:
            rc = _write_extras(extras_path=extras_path)

        deploy_args = {
            "app_id": app_id,
            "inv_dir": inv_root,
            "extras_path": deploy_extras,
            "round_index": round_index,
            "total": total,
        }
        drills = (
            rc == 0
            and round_index == 0
            and _drill_is_coming(
                app_id=app_id, inv_dir=inv_root, extras_path=extras_path
            )
        )
        if rc == 0 and meshed:
            rc = _mesh_prologue(
                app_id=app_id,
                inv_dir=inv_root,
                extras_path=deploy_extras,
                round_variants=round_variants,
            )
        if rc == 0:
            rc = _deploy(**deploy_args)
        if rc == 0:
            rc = _converge_and_verify(app_id=app_id)
        if rc == 0 and drills:
            rc = _backup_phase(
                app_id=app_id,
                inv_dir=inv_root,
                deploy_extras=deploy_extras,
                drill_extras=extras_path,
            )
        if rc == 0 and not meshed:
            rc = _reset_credentials(
                app_id=app_id, inv_dir=inv_root, round_variants=round_variants
            )
        if rc == 0:
            rc = _deploy(**deploy_args, update_pass=True)
        if rc == 0:
            rc = _converge_and_verify(app_id=app_id)
        if rc == 0 and round_index == 0:
            rc = _verify_recovered_marker(app_id=app_id)
        if rc != 0:
            return rc

    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
