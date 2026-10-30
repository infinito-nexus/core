from __future__ import annotations

import json
import os

from utils.tests.swarm.extend_inventory import drop_backup_network_mode
from utils.tests.swarm.run import run_step

_SWARM_EXTRAS_VARS = "inventories/development/swarm.yml"


def reset_target() -> int:
    nodes = [
        arg for name in ("MGR", "WRK1", "WRK2") for arg in ("--node", os.environ[name])
    ]
    return run_step(
        [
            "python3",
            "-m",
            "cli.administration.deploy.development",
            "target-reset",
            "--lab",
            os.environ["SWARM_LAB_NETWORK"],
            *nodes,
        ],
        env=os.environ.copy(),
        label="reset the shared target onto the lab",
    )


def deploy_round(
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
    from cli.administration.deploy.development.deploy.run import pin_deploy_image

    env = os.environ.copy()
    env["APP_ID"] = app_id
    pin_deploy_image(env)
    cmd = [
        "python3",
        "-m",
        "cli.administration.deploy.swarm",
        f"{inv_dir}/devices.yml",
        "-p",
        f"{inv_dir}/.password",
        "--skip-build",
        "--skip-pull",
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


def deploy_backup_host(*, app_id: str, inv_dir: str, extras_path: str) -> int:
    drop_backup_network_mode(inv_dir)
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
        "--skip-pull",
        "--skip-cleanup",
        "--skip-backup",
        "-e",
        f"@{_SWARM_EXTRAS_VARS}",
        "-e",
        f"@{extras_path}",
    ]
    return run_step(env=env, cmd=cmd, label="deploy backup host (backup.yml)")
