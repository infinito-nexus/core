from __future__ import annotations

import argparse

from cli.administration.roles.paths import WORK_DIR
from cli.administration.roles.placement import clean
from utils.cache import ROLES_DIR


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=(
            "Remove every custom role (roles/web-app-cst-*) a pull placed in this "
            "checkout and nothing else; report every other roles/web-app-cst-* entry."
        )
    ).parse_args(argv)
    try:
        lines = clean(ROLES_DIR, WORK_DIR)
    except OSError as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc
    for line in lines:
        print(f"custom role {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
