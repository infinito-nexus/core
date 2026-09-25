"""Print the bash block a role's Quick Setup documents for production.

The block is not committed: the documentation build renders Quick Setup into
its scratch checkout. CI replays the very same render, so what it executes is
by construction what a reader is told to run.

Usage:
  python -m cli.build.docs.readme.production <role> [--roles-dir DIR]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from cli.build.docs.readme.generate import _app_name, _is_invokable, _managed_blocks
from cli.build.docs.readme.sections import parse_readme
from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_README

HEADING = "### Production"
_BLOCK = re.compile(rf"^{re.escape(HEADING)}$.*?^```bash$\n(.*?)^```$", re.M | re.S)


def production_block(role_dir: Path, role_name: str) -> str:
    """Return the role's rendered production bash block.

    Args:
        role_dir: the role's directory.
        role_name: the role id.

    Returns:
        The block's body, without the fences.

    Raises:
        ValueError: the render carries no Quick Setup production block.
    """
    readme = role_dir / ROLE_FILE_README
    preamble = parse_readme(read_text(str(readme))).preamble if readme.is_file() else ""
    quick_setup = _managed_blocks(
        role_dir,
        role_name,
        _app_name(preamble, role_name),
        invokable=_is_invokable(role_name),
    ).get("Quick Setup")
    match = _BLOCK.search(quick_setup or "")
    if match is None:
        raise ValueError(f"{role_name}: Quick Setup has no {HEADING} bash block")
    return match.group(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("role")
    parser.add_argument("--roles-dir", default=str(PROJECT_ROOT / "roles"))
    args = parser.parse_args(argv)

    role_dir = Path(args.roles_dir) / args.role
    if not role_dir.is_dir():
        parser.error(f"Unknown role: {role_dir}")
    print(production_block(role_dir, args.role), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
