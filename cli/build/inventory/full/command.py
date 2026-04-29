from __future__ import annotations

import argparse
import json
import sys

from utils.cache.yaml import dump_yaml_str

from plugins.filter.get_all_invokable_apps import get_all_invokable_apps


def build_group_inventory(apps: list[str], host: str) -> dict:
    """
    Build an Ansible inventory in which each application is a group containing the given host.
    """
    groups = {app: {"hosts": [host]} for app in apps}
    inventory = {
        "all": {
            "hosts": [host],
            "children": {app: {} for app in apps},
        },
        **groups,
    }
    return inventory


def build_hostvar_inventory(apps: list[str], host: str) -> dict:
    """
    Alternative: Build an inventory where all invokable apps are set as a host variable (as a list).
    """
    return {
        "all": {"hosts": [host]},
        "_meta": {
            "hostvars": {
                host: {
                    "invokable_applications": apps,
                }
            }
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a dynamic Ansible inventory for a given host with all invokable applications."
    )
    parser.add_argument(
        "--host",
        required=True,
        help="Hostname to assign to all invokable application groups",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["json", "yaml"],
        default="yaml",
        help="Output format (yaml [default], json)",
    )
    parser.add_argument(
        "--inventory-style",
        choices=["group", "hostvars"],
        default="group",
        help="Inventory style: group (default, one group per app) or hostvars (list as hostvar)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write output to file instead of stdout",
    )
    parser.add_argument(
        "-i",
        "--ignore",
        action="append",
        default=[],
        help="Application ID(s) to ignore (can be specified multiple times or comma-separated)",
    )

    args = parser.parse_args(argv)

    try:
        apps = get_all_invokable_apps()
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    ignore_ids: set[str] = set()
    for entry in args.ignore:
        ignore_ids.update(i.strip() for i in entry.split(",") if i.strip())

    if ignore_ids:
        apps = [app for app in apps if app not in ignore_ids]

    if args.inventory_style == "group":
        inventory = build_group_inventory(apps, args.host)
    else:
        inventory = build_hostvar_inventory(apps, args.host)

    if args.format == "json":
        output = json.dumps(inventory, indent=2)
    else:
        output = dump_yaml_str(inventory)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(output)
    else:
        print(output)

    return 0
