from __future__ import annotations

import json
import os
from pathlib import Path

from utils import PROJECT_ROOT
from utils.tests.swarm.extend_inventory import (
    PROXMOX_HOST,
    drop_backup_network_mode,
    drop_network_mode,
)
from utils.tests.swarm.proxmox_host import INVENTORY as PROXMOX_INVENTORY
from utils.tests.swarm.run import run_step

_SWARM_EXTRAS_VARS = "inventories/development/swarm.yml"
_SKIPPED_MODES = ("--skip-cleanup", "--skip-backup")


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
    """Reset the shared target, then run one deploy of the round.

    Args:
        update_pass: run it as the update pass.
    """
    from cli.administration.deploy.development.deploy.run import pin_deploy_image

    rc = reset_target()
    if rc != 0:
        return rc
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
        *_SKIPPED_MODES,
        "-e",
        f"@{_SWARM_EXTRAS_VARS}",
        "-e",
        f"@{extras_path}",
        "-e",
        f"VARIANT_INDEX={json.dumps(round_index)}",
        "-e",
        f"PRIMARY_APPS={json.dumps([app_id], separators=(',', ':'))}",
    ]
    pass_label = (
        f"matrix-deploy: round {round_index + 1}/{total} "
        f"variants=[{round_index}] apps=['{app_id}']"
    )
    if update_pass:
        cmd += ["-e", "DEPLOY_IS_UPDATE=true"]
        label = f"update pass (round {round_index + 1}/{total})"
        print(f"=== {pass_label} PASS 2 (update) ===", flush=True)
    else:
        label = f"deploy round {round_index + 1}/{total}"
        print(f"=== {pass_label} PASS 1 (initial) ===", flush=True)
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
        *_SKIPPED_MODES,
        "-e",
        f"@{_SWARM_EXTRAS_VARS}",
        "-e",
        f"@{extras_path}",
    ]
    return run_step(env=env, cmd=cmd, label="deploy backup host (backup.yml)")


def deploy_proxmox_host(
    *,
    app_id: str,
    inv_dir: str,
    extras_path: str,
    round_index: int,
    update_pass: bool = False,
) -> int:
    """
    Args:
        app_id: the round's primary application.
        inv_dir: inventory directory of the round.
        extras_path: the round's deploy extras file.
        round_index: variant index of the round.
        update_pass: run it as the update pass.

    Returns:
        The exit status; 0 without a deploy when the round wrote no
        Proxmox host inventory.
    """
    inventory = Path(inv_dir) / PROXMOX_INVENTORY
    if not inventory.is_file():
        return 0
    drop_network_mode(inv_dir, PROXMOX_HOST)
    env = os.environ.copy()
    env["APP_ID"] = app_id
    cmd = [
        "python3",
        "-m",
        "cli.administration.deploy.dedicated",
        str(inventory),
        "--limit",
        PROXMOX_HOST,
        "-p",
        f"{inv_dir}/.password",
        "--skip-build",
        "--skip-pull",
        *_SKIPPED_MODES,
        "-e",
        f"@{_SWARM_EXTRAS_VARS}",
        "-e",
        f"@{extras_path}",
        "-e",
        f"VARIANT_INDEX={json.dumps(round_index)}",
        "-e",
        f"PRIMARY_APPS={json.dumps([app_id], separators=(',', ':'))}",
    ]
    if update_pass:
        cmd += ["-e", "DEPLOY_IS_UPDATE=true"]
    return run_step(env=env, cmd=cmd, label=f"deploy Proxmox host ({inventory.name})")


def sync_role(*, app_id: str, inv_dir: str, extras_path: str, round_index: int) -> int:
    """Run the role of one application again against the live cluster.

    Unlike deploy_round it leaves the shared target as it is: the sync works on
    the running stack.

    Args:
        app_id: application whose role runs again.
        inv_dir: inventory directory of the round the cluster runs.
        extras_path: the round's deploy extras file.
        round_index: variant index of that round.
    """
    from cli.administration.deploy.dedicated.command import parse_args
    from cli.administration.deploy.dedicated.modes import build_modes_from_args
    from cli.administration.deploy.dedicated.runner import deploy_ansible_playbook
    from cli.administration.deploy.development.deploy.run import pin_deploy_image

    devices = f"{inv_dir}/devices.yml"
    args, _, modes_spec = parse_args([devices, *_SKIPPED_MODES])
    env = os.environ.copy()
    env["APP_ID"] = app_id
    pin_deploy_image(env)
    cmd = [
        deploy_ansible_playbook(str(PROJECT_ROOT)),
        "-i",
        devices,
        "playbook-sync.yml",
        "-l",
        app_id,
        "--vault-password-file",
        f"{inv_dir}/.password",
        "-e",
        json.dumps(build_modes_from_args(modes_spec, args)),
        "-e",
        f"@{_SWARM_EXTRAS_VARS}",
        "-e",
        f"@{extras_path}",
        "-e",
        f"VARIANT_INDEX={json.dumps(round_index)}",
        "-e",
        f"PRIMARY_APPS={json.dumps([app_id], separators=(',', ':'))}",
        "-e",
        json.dumps({"APPLICATIONS_WHITELIST": [app_id], "sync_scope": "role"}),
    ]
    return run_step(env=env, cmd=cmd, label=f"role sync {app_id} (round {round_index})")
