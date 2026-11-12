from __future__ import annotations

import argparse
import sys
from pathlib import Path

from utils.cache.host_sync import HostSyncError, sync

FLAGS = {"true": True, "false": False}
PREFIX = "[cache-host-sync]"


def main(argv: list[str] | None = None) -> int:
    """Run ``make cache-host-sync``.

    Args:
        argv: the command line; ``sys.argv[1:]`` when None.

    Returns:
        0 once the host matches ``--sync``, 1 when the sync refused.
    """
    parser = argparse.ArgumentParser(prog="make cache-host-sync")
    parser.add_argument("--sync", required=True, choices=sorted(FLAGS))
    parser.add_argument("--shared", default="")
    parser.add_argument("--nexus", default="")
    parser.add_argument("--ubuntu-mirrors", default="")
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)
    try:
        lines = sync(
            args.root,
            enabled=FLAGS[args.sync],
            shared=args.shared,
            nexus=args.nexus,
            ubuntu_mirrors=args.ubuntu_mirrors,
        )
    except HostSyncError as exc:
        print(f"{PREFIX} {exc}", file=sys.stderr)
        return 1
    for line in lines or ["nothing recorded; the host is untouched"]:
        print(f"{PREFIX} {line}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
