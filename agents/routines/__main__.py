"""Command line for agent routines.

- ``python -m agents.routines list`` prints every routine.
- ``python -m agents.routines show <routine>`` prints the ordered steps and
  the Mermaid diagram, needing no LangGraph.
- ``python -m agents.routines run <routine>`` builds and invokes the graph.
"""

from __future__ import annotations

import argparse
import sys

from agents.routines import discover, load


def _show(name: str) -> int:
    module = load(name)
    steps = getattr(module, "STEPS", [])
    mermaid = getattr(module, "MERMAID", "")
    print(f"# {name}\n")
    for index, step in enumerate(steps, start=1):
        label = getattr(step, "label", step)
        kind = getattr(step, "kind", "")
        suffix = f"  ({kind})" if kind and kind != "deterministic" else ""
        print(f"{index}. {label}{suffix}")
    if mermaid:
        print(f"\n```mermaid\n{mermaid}\n```")
    return 0


def _run(name: str) -> int:
    module = load(name)
    graph = module.build()
    graph.invoke({})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents.routines")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("routine")
    run = sub.add_parser("run")
    run.add_argument("routine")
    args = parser.parse_args(argv)

    if args.command == "list":
        for name in discover():
            print(name)
        return 0
    try:
        if args.command == "show":
            return _show(args.routine)
        return _run(args.routine)
    except KeyError:
        print(f"no routine '{args.routine}'", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
