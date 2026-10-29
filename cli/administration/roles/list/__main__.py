from __future__ import annotations

import argparse

from cli.administration.roles.marker import placed_roles, provenance
from utils.cache import ROLES_DIR


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=(
            "Print the custom roles a pull placed under roles/ of this checkout, "
            "one per line with its source and resolved commit."
        )
    ).parse_args(argv)
    for role in placed_roles(ROLES_DIR):
        print(f"{role.name}: {provenance(role)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
