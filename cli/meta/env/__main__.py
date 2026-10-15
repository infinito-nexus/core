"""CLI entry: `python -m cli.meta.env` (also `make dotenv`)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from utils.env.builder import build_env
from utils.env.parser import parse_static_env_with_comments
from utils.env.writer import write_dotenv

from . import PROJECT_ROOT as REPO_ROOT

HOST_OWNED_KEY = "INFINITO_DOTENV_HOST_OWNED"  # nocheck: dotenv-host-owned-marker  Reason: set only by compose.yml inside the runner container; not a configuration key, a .env entry could freeze the host .env


def main(argv: list[str] | None = None) -> int:
    """Generate the env set from default.env and the runtime context.

    Args:
        argv: command-line arguments; ``--output PATH`` writes the set to PATH
            instead of the repository's ``.env``, which then stays untouched.

    Returns:
        0 on success, 2 when default.env is missing.
    """
    parser = argparse.ArgumentParser(prog="python -m cli.meta.env")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args([] if argv is None else argv)
    static_path = REPO_ROOT / "default.env"
    out_path = args.output or REPO_ROOT / ".env"
    out_name = args.output or ".env"

    if not static_path.is_file():
        print(f"ERROR: missing {static_path}", file=sys.stderr)
        return 2

    if (
        args.output is None
        and out_path.is_file()
        and os.environ.get(HOST_OWNED_KEY) == "true"
    ):
        print(
            f"Kept {out_name}: the host checkout owns it ({HOST_OWNED_KEY})",
            file=sys.stderr,
        )
        return 0

    static, static_comments = parse_static_env_with_comments(static_path)
    eb = build_env(static, repo_root=REPO_ROOT, comments=static_comments)
    write_dotenv(eb, out_path)
    print(f"Wrote {out_name} ({len(eb.values)} variables)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
