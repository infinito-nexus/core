from __future__ import annotations

import argparse
import re
import sys
import tarfile
from pathlib import Path

from yaml import YAMLError

from cli.administration.roles.paths import WORK_DIR
from cli.administration.roles.placement import pull
from utils.cache import ROLES_DIR
from utils.roles.custom import CustomRoleError

_URL_USERINFO = re.compile(r"(?<=://)[^/\s@'\"]+@")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pull the custom roles (web-app-cst-*) an inventory declares into "
            "roles/, replace the ones an earlier pull placed and remove the ones "
            "it no longer declares, without deploying."
        ),
    )
    parser.add_argument(
        "inventory",
        help="Inventory file or directory, or an inline host list such as 'localhost,'.",
    )
    return parser


def pull_or_exit(inventory: str) -> list[str]:
    """Pull the custom roles of *inventory*; exit 1 when the pull is refused.

    The reason never carries the credentials of a URL.

    Args:
        inventory: the inventory file or directory, or an inline host list.

    Returns:
        One line per placed, removed or untouched custom role; none and
        no output when nothing is declared or placed.
    """
    try:
        lines = pull(Path(inventory), ROLES_DIR, WORK_DIR)
    except (CustomRoleError, OSError, tarfile.TarError, YAMLError) as exc:
        reason = _URL_USERINFO.sub("***@", str(exc))
        print(f"\n[ERROR] Custom roles refused:\n{reason}\n", file=sys.stderr)
        sys.exit(1)
    for line in lines:
        print(f"custom role {line}", flush=True)
    return lines


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pull_or_exit(args.inventory)
    return 0
