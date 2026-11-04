from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.env.parser import parse_static_env
from utils.tests.swarm.extend_inventory import mesh_enabled
from utils.tests.swarm.run import run_step

_CONTROLLER = "localhost"
_PLAYBOOK = "playbooks/lab/mesh.yml"
_SUDO_PLAYBOOK = "playbooks/lab/passwordless-sudo.yml"
_DEFAULT_ADMIN_KEY = "/tmp/swarm-nfs-admin.key"  # noqa: S108 - ephemeral swarm-test path, overridable via KEY_PATH


def layout() -> Path:
    path = (
        os.environ.get("INFINITO_SWARM_MESHES")
        or parse_static_env(PROJECT_ROOT / "default.env")["INFINITO_SWARM_MESHES"]
    )
    return PROJECT_ROOT / path


def layout_applications() -> dict:
    document = load_yaml_any(str(layout()), default_if_missing={}) or {}
    return dict(document.get("applications") or {})


def _layout_specs() -> list:
    from cli.administration.inventory.mesh.inventory import specs_of

    return specs_of(layout_applications(), [])


def transport_mesh() -> str:
    return _layout_specs()[0].name


def stale_controller_interfaces() -> list[str]:
    specs = _layout_specs()
    declared = {spec.name for spec in specs}
    pools = {ipaddress.ip_network(spec.routed_range or spec.subnet) for spec in specs}
    listed = subprocess.run(
        ["ip", "-j", "-4", "addr", "show", "type", "wireguard"],
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted(
        link["ifname"]
        for link in json.loads(listed.stdout or "[]")
        if link.get("ifname") not in declared
        and any(
            ipaddress.ip_address(entry["local"]) in pool
            for entry in link.get("addr_info", [])
            if "local" in entry
            for pool in pools
        )
    )


_LAB_ADDRESSES = {
    "MGR": "INFINITO_SWARM_MGR_IP",
    "WRK1": "INFINITO_SWARM_WRK1_IP",
    "WRK2": "INFINITO_SWARM_WRK2_IP",
    "NFS_SERVER": "INFINITO_SWARM_NFS_IP",
    "BACKUP_NODE": "INFINITO_SWARM_BACKUP_IP",
}


def _lab_endpoints() -> list[str]:
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
    args += ["--controller", _CONTROLLER, "--controller-mesh", transport_mesh()]
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
    if not mesh_enabled():
        return 0
    escalate = [] if os.geteuid() == 0 else ["sudo", "-n"]
    for name in stale_controller_interfaces():
        rc = run_step(
            [*escalate, "ip", "link", "delete", name],
            env=os.environ.copy(),
            label=f"remove the controller's stale '{name}' interface",
        )
        if rc != 0:
            return rc
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


def switch_to_mesh_transport(*, inv_dir: str) -> int:
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
        transport_mesh(),
        user="administrator",
        private_key_file=os.environ.get("KEY_PATH") or _DEFAULT_ADMIN_KEY,
    )
    for host, address in sorted(switched.items()):
        print(f"[INFO] {host}: ansible now connects over {address}", flush=True)
    if not switched:
        print("[FATAL] no host holds a mesh address to switch to", file=sys.stderr)
        return 1
    return 0
