#!/usr/bin/env python3
"""CLI: write every declared mesh into the host_vars of its members.

Runs once over the whole host set, after the per-host provisioners have made
each ``host_vars`` file exist. That ordering is the point: the mesh is the one
credential whose values are correlated across hosts, so it needs a writer that
sees all of them at once.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from utils import PROJECT_ROOT

from .inventory import groups_of, specs_of
from .plan import plan_mesh
from .write import (
    DEFAULT_APPLICATION_ID,
    existing_public_keys,
    prune_foreign_meshes,
    write_mesh,
)

DEFAULT_GROUP_VARS = PROJECT_ROOT / "group_vars/all/21_wireguard.yml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write correlated mesh credentials into every member's host_vars."
    )
    parser.add_argument(
        "--inventory",
        action="append",
        required=True,
        help="inventory file to read group membership from; repeatable",
    )
    parser.add_argument(
        "--host-vars-dir",
        required=True,
        help="directory holding one <host>.yml per member",
    )
    parser.add_argument(
        "--vault-password-file",
        required=True,
        help="password file the private keys are encrypted with",
    )
    parser.add_argument(
        "--group-vars-file",
        default=str(DEFAULT_GROUP_VARS),
        help="file declaring WIREGUARD_MESHES",
    )
    parser.add_argument(
        "--mesh",
        action="append",
        help="restrict to this mesh name; repeatable, default all declared",
    )
    parser.add_argument(
        "--application-id",
        default=DEFAULT_APPLICATION_ID,
        help="application block the mesh is written under",
    )
    parser.add_argument(
        "--controller",
        help=(
            "host to admit as an extra spoke of --controller-mesh, so the "
            "machine driving the deploy can reach the mesh it just created"
        ),
    )
    parser.add_argument(
        "--controller-mesh",
        default="swarm",
        help="mesh --controller joins; ignored when --controller is unset",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="mint a fresh keypair for every member instead of reusing",
    )
    args = parser.parse_args(argv)

    host_vars_dir = Path(args.host_vars_dir).resolve()
    if not host_vars_dir.is_dir():
        print(f"[FATAL] host_vars dir not found: {host_vars_dir}", file=sys.stderr)
        return 1

    inventory_files = [Path(entry).resolve() for entry in args.inventory]
    groups = groups_of(inventory_files)
    if not groups:
        print(
            f"[FATAL] no groups resolved from: {', '.join(map(str, inventory_files))}",
            file=sys.stderr,
        )
        return 1

    specs = specs_of(Path(args.group_vars_file).resolve())
    if args.mesh:
        wanted = set(args.mesh)
        specs = [spec for spec in specs if spec.name in wanted]
        if not specs:
            print(f"[FATAL] no declared mesh matches {sorted(wanted)}", file=sys.stderr)
            return 1

    vault_password_file = Path(args.vault_password_file).resolve()
    all_hosts = sorted({host for hosts in groups.values() for host in hosts})

    # Exception: prune before planning. A mirrored host_vars carries another
    # host's entry for meshes this one is not a member of, and writing a
    # member's own entry never removes it.
    for host, names in sorted(
        prune_foreign_meshes(host_vars_dir, all_hosts, args.application_id).items()
    ):
        print(
            f"[INFO] {host}: dropped mesh entr(ies) owned elsewhere: {', '.join(names)}"
        )

    for spec in specs:
        mesh = plan_mesh(
            spec,
            groups,
            None
            if args.rotate
            else existing_public_keys(
                host_vars_dir,
                [host for hosts in groups.values() for host in hosts],
                spec.name,
                args.application_id,
            ),
            rotate=args.rotate,
            controller=(args.controller if spec.name == args.controller_mesh else None),
        )
        written = write_mesh(
            mesh, host_vars_dir, vault_password_file, args.application_id
        )
        minted = sum(1 for member in mesh.members if member.private_key is not None)
        print(
            f"[INFO] mesh '{spec.name}': hub {mesh.hub.host} "
            f"({mesh.hub.address}), {len(mesh.spokes)} spoke(s), "
            f"{minted} keypair(s) minted, {len(written)} host_vars written"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
