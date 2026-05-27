"""CLI entry: `python -m cli.meta.env` (also `make dotenv`)."""

from __future__ import annotations

import sys

from utils.env.builder import build_env
from utils.env.parser import parse_static_env_with_comments
from utils.env.writer import write_dotenv

from . import PROJECT_ROOT as REPO_ROOT


def main() -> int:
    static_path = REPO_ROOT / "default.env"
    out_path = REPO_ROOT / ".env"

    if not static_path.is_file():
        print(f"ERROR: missing {static_path}", file=sys.stderr)
        return 2

    static, static_comments = parse_static_env_with_comments(static_path)
    eb = build_env(static, repo_root=REPO_ROOT, comments=static_comments)
    write_dotenv(eb, out_path)
    print(
        f"Wrote {out_path.relative_to(REPO_ROOT)} ({len(eb.values)} variables)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
