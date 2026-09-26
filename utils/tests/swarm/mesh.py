"""The mesh steps of one swarm-matrix round.

Three things happen around the deploy passes when the run carries the mesh:
the cross-host writer mints it, the controller is brought onto it, and the
inventory is moved onto it so the pass that follows connects over the tunnel.
All three are no-ops when the run's vpn axis is off.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from utils.cache.yaml import dump_yaml
from utils.tests.swarm.extend_inventory import mesh_enabled
from utils.tests.swarm.run import run_step

_MESH_NAME = "swarm"
_CONTROLLER = "localhost"
_DEFAULT_ADMIN_KEY = "/tmp/swarm-nfs-admin.key"  # noqa: S108 - ephemeral swarm-test path, overridable via KEY_PATH


def write_mesh(*, inv_dir: str) -> int:
    """Write the WireGuard meshes over both inventories of the round.

    Ordered after extend_inventory, which creates the groups the meshes
    resolve from and the sibling backup.yml the data mesh spans. A no-op when
    the run's vpn axis is off, because the groups are then absent entirely.
    """
    if not mesh_enabled():
        return 0
    args = ["--inventory", f"{inv_dir}/devices.yml"]
    args += ["--inventory", f"{inv_dir}/backup.yml"]
    args += ["--host-vars-dir", f"{inv_dir}/host_vars"]
    args += ["--vault-password-file", f"{inv_dir}/.password"]
    args += ["--controller", _CONTROLLER, "--controller-mesh", _MESH_NAME]
    return run_step(
        ["python3", "-m", "cli.administration.inventory.mesh", *args],
        env=os.environ.copy(),
        label="write wireguard meshes (cross-host credentials)",
    )


def mesh_controller(*, inv_dir: str) -> int:
    """Bring the controller's own interface up before the transport moves.

    Its own play rather than a host in the deploy inventory: playbook.yml
    targets every host with become, so a controller listed there would take
    the whole host bootstrap instead of one interface.
    """
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
            "playbook-mesh-controller.yml",
        ],
        env=os.environ.copy(),
        label="put the deploy controller on the mesh",
    )


def switch_to_mesh_transport(*, inv_dir: str) -> int:
    """Point the inventory at the mesh before the pass that must use it.

    The first pass reaches the nodes over the container connection, because it
    is what brings the mesh up. Every pass after it connects over the mesh, so
    a broken tunnel fails the deploy at the connection instead of letting a
    role quietly fall back to the underlay.
    """
    if not mesh_enabled():
        return 0
    from cli.administration.inventory.mesh.transport import switch_to_mesh

    host_vars = Path(inv_dir) / "host_vars"
    hosts = sorted(path.stem for path in host_vars.glob("*.yml"))
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
