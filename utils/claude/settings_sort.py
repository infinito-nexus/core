#!/usr/bin/env python3
"""Sort the curated string arrays in ``.claude/settings.json``.

The lint test in
``tests/lint/repository/settings/test_claude_sorted.py`` requires every
hand-curated array to stay ASCII-sorted ascending so diffs stay
reviewable and merge conflicts stay minimal. Tools that auto-extend the
file (e.g. permission auto-allowlists) tend to append unsorted; this
script puts everything back in order.

Exit code is ``0`` if the file was already sorted (no write), ``0``
after a successful rewrite, ``1`` on read/parse failure.
"""

from __future__ import annotations

import json
import sys

from . import PROJECT_ROOT

SETTINGS_PATH = PROJECT_ROOT / ".claude" / "settings.json"

SORTED_ARRAYS: list[tuple[str, ...]] = [
    ("permissions", "allow"),
    ("permissions", "deny"),
    ("permissions", "ask"),
    ("sandbox", "network", "allowedDomains"),
    ("sandbox", "filesystem", "allowWrite"),
    ("sandbox", "filesystem", "denyRead"),
]


def _resolve(data: dict, path: tuple[str, ...]):
    obj = data
    for key in path:
        if not isinstance(obj, dict) or key not in obj:
            return None
        obj = obj[key]
    return obj


def main() -> int:
    try:
        raw = SETTINGS_PATH.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read — CLI reads SETTINGS_PATH then writes back sorted; cache would mask the rewrite
    except OSError as exc:
        print(f"error: cannot read {SETTINGS_PATH}: {exc}", file=sys.stderr)
        return 1

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: cannot parse {SETTINGS_PATH}: {exc}", file=sys.stderr)
        return 1

    changed = False
    for path in SORTED_ARRAYS:
        arr = _resolve(data, path)
        if not isinstance(arr, list):
            continue
        ordered = sorted(arr)
        if ordered != arr:
            arr[:] = ordered
            changed = True
            print(f"sorted: {'.'.join(path)} ({len(arr)} entries)")

    if not changed:
        print(f"{SETTINGS_PATH.relative_to(PROJECT_ROOT)} already sorted.")
        return 0

    SETTINGS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"updated {SETTINGS_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
