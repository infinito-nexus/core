"""Render the header-trust table from the roles into rbac.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli.build.docs.header_trust import render, replace_block
from utils.cache.files import read_text
from utils.roles.header_trust import (
    header_trust_declarations,
    header_trust_exemptions,
    header_trust_headers,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="infinito build docs header_trust",
        description=(
            "Render the header-trust roles, their proxy secrets and switches "
            "into rbac.md for the docs build."
        ),
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--roles-dir", required=True)
    args = parser.parse_args(argv)

    roles_dir = Path(args.roles_dir)
    block = render(
        header_trust_headers(roles_dir),
        header_trust_declarations(roles_dir),
        header_trust_exemptions(roles_dir),
    )
    path = Path(args.doc)
    path.write_text(replace_block(read_text(str(path)), block), "utf-8")
    print(f"{path.name}: header-trust table rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
