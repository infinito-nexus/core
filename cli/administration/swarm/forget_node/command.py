"""Forget a permanently lost Swarm node, then re-run the normal deploy.

    infinito administration swarm forget_node <inventory> --host <name> \
        [deploy options, e.g. --password-file <file>]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Mapping

from utils import PROJECT_ROOT
from utils.roles.forget_node import ForgetNodeError, assert_host_absent


def inventory_hosts(listing: Mapping) -> set[str]:
    """Return every host of an ``ansible-inventory --list`` document.

    Args:
        listing: parsed JSON of ``ansible-inventory --list``.
    """
    hosts = set((listing.get("_meta") or {}).get("hostvars") or {})
    for name, group in listing.items():
        if name != "_meta" and isinstance(group, Mapping):
            hosts.update(group.get("hosts") or [])
    return hosts


def load_inventory_hosts(inventory: str) -> set[str]:
    result = subprocess.run(
        ["ansible-inventory", "-i", inventory, "--list"],
        check=True,
        capture_output=True,
        text=True,
    )
    return inventory_hosts(json.loads(result.stdout))


def deploy_command(inventory: str, host: str, passthrough: list[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "cli.administration.deploy.swarm",
        inventory,
        *passthrough,
        "-e",
        f"SWARM_FORGET_NODE={host}",
    ]


def main(
    argv: list[str] | None = None,
    *,
    load_hosts: Callable[[str], set[str]] = load_inventory_hosts,
    run: Callable[[list[str]], int] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="infinito administration swarm forget_node",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("inventory", help="Inventory file or directory.")
    parser.add_argument(
        "--host", required=True, help="Swarm node hostname of the lost node."
    )
    args, passthrough = parser.parse_known_args(argv)

    try:
        assert_host_absent(args.host, load_hosts(args.inventory))
    except ForgetNodeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    cmd = deploy_command(args.inventory, args.host, passthrough)
    if run is None:
        return subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False).returncode
    return run(cmd)
