#!/usr/bin/env python3
"""CLI: write every declared mesh into the host_vars of its members."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from utils import PROJECT_ROOT

from .inventory import groups_of, specs_of
from .plan import plan_mesh
from .write import (
    DEFAULT_APPLICATION_ID,
    existing_addresses,
    existing_public_keys,
    prune_foreign_meshes,
    write_mesh,
)

DEFAULT_GROUP_VARS = PROJECT_ROOT / "group_vars/all/21_wireguard.yml"


def parse_endpoints(pairs: list[str]) -> dict[str, str]:
    """Turn ``HOST=ADDRESS`` arguments into the map the planner takes."""
    endpoints: dict[str, str] = {}
    for pair in pairs:
        host, separator, address = pair.partition("=")
        if not separator or not host.strip() or not address.strip():
            raise SystemExit(f"--endpoint expects HOST=ADDRESS, got {pair!r}")
        endpoints[host.strip()] = address.strip()
    return endpoints


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
        "--endpoint",
        action="append",
        default=[],
        metavar="HOST=ADDRESS",
        help=(
            "underlay address peers dial for HOST, for a topology whose "
            "inventory names do not resolve on every member. Repeatable; a "
            "host left out is dialled by its inventory name"
        ),
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
    all_hosts = sorted(
        {host for hosts in groups.values() for host in hosts}
        | ({args.controller} if args.controller else set())
    )

    for host, names in sorted(
        prune_foreign_meshes(host_vars_dir, all_hosts, args.application_id).items()
    ):
        print(
            f"[INFO] {host}: dropped mesh entr(ies) owned elsewhere: {', '.join(names)}"
        )

    keyed_here: dict[str, str] = {}
    for spec in specs:
        held = (
            {}
            if args.rotate
            else existing_public_keys(
                host_vars_dir,
                all_hosts,
                spec.name,
                args.application_id,
            )
        )
        held.update(keyed_here)
        mesh = plan_mesh(
            spec,
            groups,
            held,
            controller=(args.controller if spec.name == args.controller_mesh else None),
            endpoints=parse_endpoints(args.endpoint),
            addresses=existing_addresses(
                host_vars_dir,
                all_hosts,
                spec.name,
                args.application_id,
            ),
        )
        keyed_here.update({member.host: member.public_key for member in mesh.members})
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
