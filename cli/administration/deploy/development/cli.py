from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def _module_exists(fullname: str) -> bool:
    return importlib.util.find_spec(fullname) is not None


def _try_import(fullname: str):
    """
    Import module if it exists, else return None.
    """
    if not _module_exists(fullname):
        return None
    return importlib.import_module(fullname)


def _iter_command_modules(base_pkg: str, names: Iterable[str]):
    """
    Yield imported command modules that implement add_parser(sub).
    """
    for name in names:
        m = _try_import(f"{base_pkg}.{name}")
        if m is None:
            continue
        if hasattr(m, "add_parser"):
            yield name, m


def _build_parser(base_pkg: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=f"python -m {base_pkg}",
        description="Infinito.Nexus development compose stack helper.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # Keep this list explicit (predictable UX), but tolerate missing modules.
    command_names = [
        "up",
        "down",
        "stop",
        "restart",
        "build",
        "init",
        "deploy",
        "run",
        "exec",
        "logs",
    ]

    for _, mod in _iter_command_modules(base_pkg, command_names):
        mod.add_parser(sub)

    return p


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    base_pkg = __package__ or "cli.administration.deploy.development"
    parser = _build_parser(base_pkg)

    args = parser.parse_args(argv)

    handler = getattr(args, "_handler", None)
    if handler is None:
        # This should not happen if each subparser sets _handler, but keep it safe.
        raise SystemExit(
            f"Command '{getattr(args, 'command', '<unknown>')}' has no handler"
        )

    return int(handler(args))
