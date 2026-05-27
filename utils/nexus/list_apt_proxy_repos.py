#!/usr/bin/env python3
"""Filter Nexus `/service/rest/v1/repositories` JSON (stdin) down to
apt-format proxy repo names, one per line (stdout). Exit 1 if no
matching repo is found or input is malformed.
"""

import json
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 1
    if not isinstance(data, list):
        return 1
    names = [
        r["name"]
        for r in data
        if isinstance(r, dict)
        and r.get("format") == "apt"
        and r.get("type") == "proxy"
        and isinstance(r.get("name"), str)
        and r["name"]
    ]
    if not names:
        return 1
    print("\n".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
