from __future__ import annotations

import argparse

from .stop import handler as stop_handler
from .up import handler as up_handler


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "restart",
        help="Restart the compose stack: stop -> up (no force by default).",
    )

    p.add_argument(
        "--skip-entry-init",
        action="store_true",
        help="Do not run entry.sh init after stack is up.",
    )

    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    # 1) stop (best-effort)
    stop_rc = stop_handler(argparse.Namespace())
    if stop_rc != 0:
        print(f">>> WARNING: stop returned rc={stop_rc}, continuing with up")

    # 2) up (normal behavior, no force unless flags provided)
    up_args = argparse.Namespace(
        skip_entry_init=bool(args.skip_entry_init),
        when_down=False,  # REQUIRED by up.handler()
    )
    return int(up_handler(up_args))
