"""Print the architecture pool of one run as a JSON array.

Usage:
  python -m cli.meta.ci.architectures ["amd64 arm64"]
"""

from __future__ import annotations

import json
import sys

from utils.github.variant.pools import resolve_architectures


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    print(json.dumps(list(resolve_architectures(args[0] if args else ""))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
