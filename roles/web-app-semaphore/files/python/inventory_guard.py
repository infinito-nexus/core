from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT = "inventory_guard.py"
MARKERS = ("{{", "{%", "{#")
CORE_VARS = ("group_vars", "all")
INVENTORY_SETTINGS = frozenset({"DEPLOYMENT_MODE", "DOMAIN_PRIMARY", "TLS_ENABLED"})


def templates(value, where="inventory"):
    """Args:
    value: the inventory as ``ansible-inventory --list`` prints it, or a
        part of it.
    where: the place ``value`` sits at, as the findings name it.

    Returns:
        The place of every key and string holding a Jinja marker, never the
        value itself. Ansible renders such a string on the runner when a task
        reads it, where a lookup runs a command, reads a file or the task's
        environment, or reaches the runner's network.
    """
    if isinstance(value, str):
        return [where] if any(marker in value for marker in MARKERS) else []
    if isinstance(value, dict):
        found = []
        for key, item in value.items():
            found += templates(str(key), f"{where} key {key!r}")
            found += templates(item, f"{where}.{key}")
        return found
    if isinstance(value, list):
        return [
            hit
            for index, item in enumerate(value)
            for hit in templates(item, f"{where}[{index}]")
        ]
    return []


def core_settings(core):
    """Args:
    core: the core tree of the runner image.

    Returns:
        The top-level names of its ``group_vars/all`` files.
    """
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    from utils.cache.yaml import load_yaml_any

    names = set()
    for path in sorted(core.joinpath(*CORE_VARS).glob("*.yml")):
        names.update(load_yaml_any(str(path)))
    return frozenset(names)


def shadowing(inventory, settings):
    """Args:
    inventory: the inventory as ``ansible-inventory --list`` prints it.
    settings: the names of ``core_settings``.

    Returns:
        Every host or group variable that shadows a core setting outside
        ``INVENTORY_SETTINGS``. An inventory variable outranks the
        ``group_vars/all`` of the playbook, so a ``STACK_HOST: localhost``
        sends every ``delegate_to`` task over the local connection of the
        runner and a ``MASK_CREDENTIALS_IN_LOGS: false`` prints credentials
        into the task log.
    """
    refused = settings - INVENTORY_SETTINGS
    found = []
    for host, variables in sorted(
        inventory.get("_meta", {}).get("hostvars", {}).items()
    ):
        found += [
            f"_meta.hostvars.{host}.{name} shadows a core setting"
            for name in sorted(refused & set(variables))
        ]
    for group, entry in sorted(inventory.items()):
        if isinstance(entry, dict) and isinstance(entry.get("vars"), dict):
            found += [
                f"{group}.vars.{name} shadows a core setting"
                for name in sorted(refused & set(entry["vars"]))
            ]
    return found


def main(stdin, stderr, core):
    """Args:
    stdin: the inventory as ``ansible-inventory --list`` prints it.
    stderr: where a refusal goes.
    core: the core tree of the runner image.

    Returns:
        0 when the inventory holds no Jinja marker and shadows no core
        setting, 1 on a refusal.
    """
    try:
        inventory = json.load(stdin)
    except ValueError as error:
        found = [f"the inventory is no JSON: {error}"]
    else:
        if isinstance(inventory, dict):
            found = templates(inventory) + shadowing(inventory, core_settings(core))
        else:
            found = ["the inventory is no mapping"]
    if found:
        print(
            f"{SCRIPT}: the inventory would reach past the core tree on the runner: "
            + "; ".join(found),
            file=stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin, sys.stderr, Path(sys.argv[1])))
