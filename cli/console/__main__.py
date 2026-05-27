"""Interactive REPL for the infinito.nexus CLI (runs on the host)."""

from __future__ import annotations

import sys


def _print_help() -> None:
    print("usage: infinito console")
    print()
    print("Interactive REPL that forwards each line to the infinito CLI.")
    print("Strips a leading 'infinito'/'cli' prefix, treats 'help'/'?' as --help,")
    print("ignores Ctrl+C; exits on 'exit', 'quit', ':q', or Ctrl+D.")


if __name__ == "__main__":
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        _print_help()
        raise SystemExit(0)
    from cli.console.repl import main

    raise SystemExit(main())
