"""Read what the mesh CLI wrote, for the svc-net-wireguard CLI test.

Usage:
  python mesh.py address <host_vars_dir> <host> <mesh>
  python mesh.py ssh-args

Args:
  address: print the address <host> holds on <mesh>, or nothing.
  ssh-args: print the SSH options a mesh hop uses, one per line.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from cli.administration.inventory.mesh.transport import (
    mesh_address,
    mesh_ssh_args,
    repo_ssh_args,
)


def main(argv: list[str]) -> int:
    command, *args = argv
    if command == "address":
        host_vars_dir, host, mesh = args
        print(mesh_address(Path(host_vars_dir), host, mesh) or "")
        return 0
    if command == "ssh-args":
        print("\n".join(shlex.split(mesh_ssh_args(repo_ssh_args()))))
        return 0
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
