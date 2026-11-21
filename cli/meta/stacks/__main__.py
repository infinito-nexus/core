from __future__ import annotations

import argparse
import json
import sys

from utils.stacks.declaration import load, problems, resolve
from utils.stacks.makefile import makefile_calls


def main(argv: list[str] | None = None) -> int:
    """Print the stacks a make target starts, without starting any.

    Args:
        argv: the make target, as the only argument.
    """
    parser = argparse.ArgumentParser(
        description="Print the stacks a make target starts (dry run)."
    )
    parser.add_argument("target")
    args = parser.parse_args(argv)
    stacks = load()
    graph = makefile_calls()
    broken = problems(stacks, set(graph))
    if broken:
        print("[stacks] " + "; ".join(broken), file=sys.stderr)
        return 2
    try:
        names = resolve(args.target, stacks, graph)
    except KeyError:
        print(f"[stacks] the Makefile defines no target {args.target}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "target": args.target,
                "stacks": [{"name": n, "class": stacks[n].lifecycle} for n in names],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
