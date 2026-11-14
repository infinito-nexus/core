from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache import PROJECT_ROOT

from .compose import Compose
from .env import resolve_distro

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def down_stack(*, repo_root: Path, distro: str) -> None:
    Compose(repo_root=repo_root, distro=distro).down()


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("down", help="Stop compose stack and remove volumes.")
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    down_stack(repo_root=PROJECT_ROOT, distro=resolve_distro())
    return 0
