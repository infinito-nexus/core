"""Render the lifecycle diagram from meta/lifecycle.yml into lifecycle.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli.build.docs.lifecycle import DOC, render, replace_block
from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.lifecycle import load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="infinito build docs lifecycle",
        description=(
            "Render the lifecycle diagram from meta/lifecycle.yml into "
            "lifecycle.md for the docs build."
        ),
    )
    parser.add_argument("--doc", default=str(PROJECT_ROOT / DOC))
    args = parser.parse_args(argv)

    path = Path(args.doc)
    path.write_text(replace_block(read_text(str(path)), render(load())), "utf-8")
    print(f"{path.name}: lifecycle diagram rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
