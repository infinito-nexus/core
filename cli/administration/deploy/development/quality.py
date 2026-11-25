from __future__ import annotations

import argparse

from .common import make_compose

SERVICE = "quality"
PROFILE = "tools"


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "quality",
        help="Run quality in its compose service (profile tools) against this checkout.",
    )
    p.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments for quality, such as: -- check --staged.",
    )
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    quality_args = args.args[1:] if args.args[:1] == ["--"] else list(args.args)
    if not quality_args:
        raise SystemExit("quality needs its arguments, such as: -- check --staged")
    r = make_compose().run(
        ["--profile", PROFILE, "run", "--rm", SERVICE, *quality_args], check=False
    )
    return int(r.returncode)
