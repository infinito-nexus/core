"""The mesh steps of one swarm-matrix round."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from utils.cache.yaml import dump_yaml
from utils.tests.swarm.extend_inventory import mesh_enabled
from utils.tests.swarm.run import run_step

_MESH_NAME = "swarm"
_CONTROLLER = "localhost"
_PLAYBOOK = "playbook-mesh.yml"
_BENCH_PLAYBOOK = "transport-bench.yml"
_SUDO_PLAYBOOK = "lab-sudo.yml"
_SWARM_EXTRAS_VARS = "inventories/development/swarm.yml"
_DEFAULT_ADMIN_KEY = "/tmp/swarm-nfs-admin.key"  # noqa: S108 - ephemeral swarm-test path, overridable via KEY_PATH

_LAB_ADDRESSES = {
    "MGR": "INFINITO_SWARM_MGR_IP",
    "WRK1": "INFINITO_SWARM_WRK1_IP",
    "WRK2": "INFINITO_SWARM_WRK2_IP",
    "NFS_SERVER": "INFINITO_SWARM_NFS_IP",
    "BACKUP_NODE": "INFINITO_SWARM_BACKUP_IP",
}


def _lab_endpoints() -> list[str]:
    """`--endpoint` argument per lab node, from the topology default.env names."""
    arguments: list[str] = []
    for name_var, address_var in _LAB_ADDRESSES.items():
        name = os.environ.get(name_var, "").strip()
        address = os.environ.get(address_var, "").strip()
        if name and address:
            arguments += ["--endpoint", f"{name}={address}"]
    return arguments


def write_mesh(*, inv_dir: str, rotate: bool = False) -> int:
    """Write the WireGuard meshes over both inventories of the round.

    Args:
        inv_dir: inventory directory of the round.
        rotate: mint a fresh keypair for every member.
    """
    if not mesh_enabled():
        return 0
    args = ["--inventory", f"{inv_dir}/devices.yml"]
    args += ["--inventory", f"{inv_dir}/backup.yml"]
    args += ["--host-vars-dir", f"{inv_dir}/host_vars"]
    args += ["--vault-password-file", f"{inv_dir}/.password"]
    args += ["--controller", _CONTROLLER, "--controller-mesh", _MESH_NAME]
    args += _lab_endpoints()
    if rotate:
        args += ["--rotate"]
    label = "rotate the wireguard meshes" if rotate else "write wireguard meshes"
    return run_step(
        ["python3", "-m", "cli.administration.inventory.mesh", *args],
        env=os.environ.copy(),
        label=f"{label} (cross-host credentials)",
    )


def bootstrap_mesh(*, inv_dir: str) -> int:
    """Bring the mesh up before anything is deployed over it."""
    if not mesh_enabled():
        return 0
    return run_step(
        [
            "ansible-playbook",
            "-i",
            f"{inv_dir}/devices.yml",
            "--vault-password-file",
            f"{inv_dir}/.password",
            "-e",
            "MESH_BOOTSTRAP=true",
            _PLAYBOOK,
        ],
        env=os.environ.copy(),
        label="bootstrap the mesh before the deploy",
    )


def converge_mesh(*, inv_dir: str) -> int:
    """Carry the rotated keys to every node before the transport moves."""
    if not mesh_enabled():
        return 0
    return run_step(
        [
            "ansible-playbook",
            "-i",
            f"{inv_dir}/devices.yml",
            "--vault-password-file",
            f"{inv_dir}/.password",
            _PLAYBOOK,
        ],
        env=os.environ.copy(),
        label="converge the mesh on every node",
    )


def mesh_controller(*, inv_dir: str) -> int:
    """Bring the controller's own interface up before the transport moves."""
    if not mesh_enabled():
        return 0
    inventory = Path(inv_dir) / "controller.yml"
    dump_yaml(
        str(inventory),
        {
            "all": {
                "children": {
                    "svc-net-wireguard": {
                        "hosts": {_CONTROLLER: {"ansible_connection": "local"}}
                    }
                }
            }
        },
    )
    return run_step(
        [
            "ansible-playbook",
            "-i",
            str(inventory),
            "--vault-password-file",
            f"{inv_dir}/.password",
            _PLAYBOOK,
        ],
        env=os.environ.copy(),
        label="put the deploy controller on the mesh",
    )


def lab_sudo_without_prompt(*, inv_dir: str) -> int:
    """Take the sudo prompt off the lab's administrator before the switch.

    Measured over the mesh, an escalated module call costs 1046ms more than an
    unescalated one, while over the container connection -- which runs as root
    and so never prompts -- escalation is free. The prompt, not the transport,
    is what the meshed arm was paying: SSH through the tunnel is itself faster
    per call than docker exec.

    Runs while the inventory still reaches the nodes as root, so it is in place
    before anything logs in as the administrator.

    Args:
        inv_dir: inventory directory of the round.
    """
    if not mesh_enabled():
        return 0
    return run_step(
        [
            "ansible-playbook",
            "-i",
            f"{inv_dir}/devices.yml",
            "--vault-password-file",
            f"{inv_dir}/.password",
            _SUDO_PLAYBOOK,
        ],
        env=os.environ.copy(),
        label="take the sudo prompt off the lab administrator",
    )


def transport_bench(*, inv_dir: str, extras_path: str, label: str) -> int:
    """Time a fixed number of module calls over whatever transport is in force.

    Run once before the transport switch and once after, the four task
    durations decompose the meshed arm's per-task cost into the connection
    plugin and the privilege escalation. Off unless asked for, and its exit
    code never reaches the round: a diagnostic must not decide whether a
    deploy passes.

    Args:
        inv_dir: inventory directory of the round.
        extras_path: round extras, which carry the become password the
            escalated half of the benchmark needs.
        label: which transport the numbers belong to, for the banner.
    """
    if (os.environ.get("INFINITO_SWARM_TRANSPORT_BENCH") or "").strip().lower() != "true":
        return 0
    run_step(
        [
            "ansible-playbook",
            "-i",
            f"{inv_dir}/devices.yml",
            "--vault-password-file",
            f"{inv_dir}/.password",
            "-e",
            f"@{_SWARM_EXTRAS_VARS}",
            "-e",
            f"@{extras_path}",
            _BENCH_PLAYBOOK,
        ],
        env=os.environ.copy(),
        label=f"transport benchmark ({label})",
    )
    return 0


def switch_to_mesh_transport(*, inv_dir: str) -> int:
    """Point the inventory at the mesh before the pass that must use it."""
    if not mesh_enabled():
        return 0
    from cli.administration.inventory.mesh.transport import switch_to_mesh

    host_vars = Path(inv_dir) / "host_vars"
    hosts = sorted(
        path.stem for path in host_vars.glob("*.yml") if path.stem != _CONTROLLER
    )
    switched = switch_to_mesh(
        host_vars,
        hosts,
        _MESH_NAME,
        user="administrator",
        private_key_file=os.environ.get("KEY_PATH") or _DEFAULT_ADMIN_KEY,
    )
    for host, address in sorted(switched.items()):
        print(f"[INFO] {host}: ansible now connects over {address}", flush=True)
    if not switched:
        print("[FATAL] no host holds a mesh address to switch to", file=sys.stderr)
        return 1
    return 0
