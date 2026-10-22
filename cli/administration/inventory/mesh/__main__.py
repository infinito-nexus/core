#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .inventory import declared_specs, groups_of, topology_of
from .plan import plan_mesh, primary_meshes
from .write import (
    existing_addresses,
    existing_public_keys,
    prune_foreign_meshes,
    write_mesh,
)


def parse_pairs(pairs: list[str], flag: str, value_name: str) -> dict[str, str]:
    """HOST=VALUE pairs as a mapping.

    Args:
        pairs: the raw values of a repeatable flag.
        flag: the flag the pairs came from, for the error message.
        value_name: what the right-hand side names, for the error message.
    """
    parsed: dict[str, str] = {}
    for pair in pairs:
        host, separator, value = pair.partition("=")
        if not separator or not host.strip() or not value.strip():
            raise SystemExit(f"{flag} expects HOST={value_name}, got {pair!r}")
        parsed[host.strip()] = value.strip()
    return parsed


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
        help=(
            "directory holding one <host>.yml per member; the meshes and their "
            "members are read from the applications block there"
        ),
    )
    parser.add_argument(
        "--vault-password-file",
        required=True,
        help="password file the private keys are encrypted with",
    )
    parser.add_argument(
        "--host-vault-password-file",
        action="append",
        default=[],
        metavar="HOST=FILE",
        help=(
            "password file HOST's own private key is encrypted with, for a host "
            "deployed with its own vault password; repeatable, a host left out "
            "uses --vault-password-file"
        ),
    )
    parser.add_argument(
        "--mesh",
        action="append",
        help="restrict to this mesh name; repeatable, default all declared",
    )
    parser.add_argument(
        "--controller",
        help="host to admit as an extra spoke of --controller-mesh",
    )
    parser.add_argument(
        "--controller-mesh",
        help=(
            "mesh --controller joins, default the first declared; ignored when "
            "--controller is unset"
        ),
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        metavar="HOST=ADDRESS",
        help=(
            "underlay address peers dial for HOST; repeatable, a host left out "
            "is dialled by its inventory name"
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

    try:
        declared = declared_specs(groups, host_vars_dir, inventory_files)
        topology = topology_of(groups, host_vars_dir, declared)
    except (TypeError, ValueError) as error:
        print(f"[FATAL] {error}", file=sys.stderr)
        return 1

    controller_mesh = args.controller_mesh or declared[0].name
    if args.controller and controller_mesh not in {spec.name for spec in declared}:
        print(
            f"[FATAL] --controller-mesh {controller_mesh!r} is not a declared mesh",
            file=sys.stderr,
        )
        return 1
    primary = primary_meshes(declared, topology, args.controller, controller_mesh)

    specs = declared
    if args.mesh:
        wanted = set(args.mesh)
        specs = [spec for spec in specs if spec.name in wanted]
        if not specs:
            print(f"[FATAL] no declared mesh matches {sorted(wanted)}", file=sys.stderr)
            return 1

    vault_password_file = Path(args.vault_password_file).resolve()
    host_vault_password_files = {
        host: Path(path).resolve()
        for host, path in parse_pairs(
            args.host_vault_password_file, "--host-vault-password-file", "FILE"
        ).items()
    }
    missing = sorted(
        str(path) for path in host_vault_password_files.values() if not path.is_file()
    )
    if missing:
        print(
            f"[FATAL] vault password file(s) not found: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1
    endpoints = parse_pairs(args.endpoint, "--endpoint", "ADDRESS")
    all_hosts = sorted(
        {host for hosts in groups.values() for host in hosts}
        | ({args.controller} if args.controller else set())
    )

    keyed_here: dict[str, str] = {}
    meshes = []
    for spec in specs:
        held = (
            {}
            if args.rotate
            else existing_public_keys(host_vars_dir, all_hosts, spec.name)
        )
        held.update(keyed_here)
        try:
            mesh = plan_mesh(
                spec,
                topology,
                held,
                controller=(args.controller if spec.name == controller_mesh else None),
                endpoints=endpoints,
                addresses=existing_addresses(host_vars_dir, all_hosts, spec.name),
            )
        except ValueError as error:
            print(f"[FATAL] {error}", file=sys.stderr)
            return 1
        keyed_here.update({member.host: member.public_key for member in mesh.members})
        meshes.append(mesh)

    for host, names in sorted(prune_foreign_meshes(host_vars_dir, all_hosts).items()):
        print(
            f"[INFO] {host}: dropped mesh entr(ies) owned elsewhere: {', '.join(names)}"
        )

    for mesh in meshes:
        written = write_mesh(
            mesh,
            host_vars_dir,
            vault_password_file,
            primary,
            host_vault_password_files=host_vault_password_files,
        )
        minted = sum(1 for member in mesh.members if member.private_key is not None)
        roaming = sum(1 for member in mesh.spokes if member.roaming)
        shape = (
            f"full mesh of {len(mesh.members)} member(s)"
            if mesh.is_full
            else f"hub {mesh.hub.host} ({mesh.hub.address}), "
            f"{len(mesh.spokes)} spoke(s)"
            + (f" ({roaming} roaming)" if roaming else "")
        )
        print(
            f"[INFO] mesh '{mesh.spec.name}': {shape}, "
            f"{minted} keypair(s) minted, {len(written)} host_vars written"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
