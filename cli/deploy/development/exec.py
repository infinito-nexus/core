from __future__ import annotations

import argparse
import os

from .common import make_compose


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("exec", help="Execute a command inside the infinito container.")
    p.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Inject KEY=VALUE into the container environment for this "
            "exec call. Repeatable. Lets bash callers pass per-run "
            "context (INVENTORY_FILE, APPS, ...) into in-container "
            "helper scripts without inlining heredocs."
        ),
    )
    p.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command to execute (use `--` to separate).",
    )
    p.set_defaults(_handler=handler)


def _parse_env_pairs(pairs: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--env expects KEY=VALUE; got {pair!r} without '='")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"--env KEY is empty in {pair!r}")
        parsed[key] = value
    return parsed


def handler(args: argparse.Namespace) -> int:
    compose = make_compose()

    cmd = list(args.cmd or [])
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        raise SystemExit("exec requires a command (e.g. exec -- sh -lc 'whoami')")

    extra_env: dict[str, str] = {}
    services_disabled = os.environ.get("SERVICES_DISABLED", "")
    if services_disabled:
        extra_env["SERVICES_DISABLED"] = services_disabled

    # Caller-supplied --env entries win over implicit ones (current convention
    # in the dev CLI: explicit user input overrides implicit defaults).
    extra_env.update(_parse_env_pairs(args.env or []))

    r = compose.exec(cmd, check=False, extra_env=extra_env or None)
    return int(r.returncode)
