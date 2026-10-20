from __future__ import annotations

import argparse
import json
import subprocess

from .common import make_compose
from .up import handler as up_handler


def foreign_endpoints(rows: str, project: str) -> list[str]:
    """Return the running containers of other projects on the network.

    Args:
        rows: ``docker ps`` lines of ``<name>\\t<compose project>``.
        project: compose project that owns the network.
    """
    names = []
    for row in rows.splitlines():
        name, _, owner = row.partition("\t")
        if name and owner != project:
            names.append(name)
    return names


def _docker(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["docker", *args], check=True, capture_output=capture, text=True
    )
    return result.stdout if capture else ""


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "recreate",
        help="Recreate the default network, keeping volumes and foreign stacks.",
    )
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    compose = make_compose()
    rendered = compose.run(["config", "--format", "json"], capture=True).stdout
    config = json.loads(rendered)
    project = config["name"]
    network = config["networks"]["default"]["name"]

    rows = _docker(
        "ps",
        "--filter",
        f"network={network}",
        "--format",
        '{{.Names}}\t{{.Label "com.docker.compose.project"}}',
        capture=True,
    )
    detached = foreign_endpoints(rows, project)
    for name in detached:
        print(f">>> Detaching {name} from {network}")
        _docker("network", "disconnect", network, name)

    rc = 1
    try:
        compose.run(["down", "--remove-orphans"])
        rc = up_handler(argparse.Namespace(skip_entry_init=False, when_down=False))
    finally:
        if rc != 0 and detached:
            print(f">>> Still detached from {network}: {' '.join(detached)}")
    if rc != 0:
        return rc

    for name in detached:
        print(f">>> Attaching {name} to {network}")
        _docker("network", "connect", network, name)
    return 0
