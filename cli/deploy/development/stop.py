from __future__ import annotations

import argparse

from .common import make_compose


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "stop",
        help="Stop services in the compose stack (no volume removal).",
    )
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    compose = make_compose()
    r = compose.run(["stop"], check=False)
    return int(r.returncode)
