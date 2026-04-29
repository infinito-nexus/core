from __future__ import annotations

import argparse

from .common import make_compose


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "logs", help="Show docker compose logs for the development stack."
    )
    p.add_argument("--tail", type=int, default=200, help="Tail N lines (default: 200).")
    p.add_argument("-f", "--follow", action="store_true", help="Follow logs.")
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    compose = make_compose()

    cmd = ["logs", f"--tail={int(args.tail)}"]
    if args.follow:
        cmd.append("-f")

    r = compose.run(cmd, check=False)
    return int(r.returncode)
