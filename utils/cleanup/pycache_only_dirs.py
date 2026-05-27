"""Remove directories whose only child is a ``__pycache__`` folder.

Such directories show up after Python test modules / source files are moved or
deleted: the ``__pycache__`` cache remains and the now-orphan parent directory
holds nothing else. ``git clean -fdX`` does not touch the parent because the
parent itself is tracked, so they stick around forever.

Run via ``python -m utils.cleanup.pycache_only_dirs`` (or ``make clean-pycache-dirs``).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_SKIP_PARTS = frozenset({".git", ".venv", "venv", "node_modules"})


def _depth(path: str) -> int:
    return path.count(os.sep)


def main() -> int:
    root = Path()
    removed = 0
    # Post-order: deepest directories first so emptying a child can collapse
    # its parent on a subsequent pass through the sorted list.
    for d, _dirs, _files in sorted(os.walk(root), key=lambda t: -_depth(t[0])):
        p = Path(d)
        if p == root or p.name == "__pycache__":
            continue
        if any(part in _SKIP_PARTS for part in p.parts):
            continue
        if not p.is_dir():
            continue
        try:
            entries = [c.name for c in p.iterdir()]
        except PermissionError as e:
            print(f"skipped (unreadable) {p}: {e}", file=sys.stderr)
            continue
        if entries != ["__pycache__"]:
            continue
        try:
            shutil.rmtree(p)
        except PermissionError as e:
            print(f"skipped (no perm) {p}: {e}", file=sys.stderr)
            continue
        removed += 1
        print(f"removed {p}", file=sys.stderr)
    print(f"done: {removed} dir(s) removed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
