"""Compatibility wrapper.

This package was migrated from a flat module (inventory/__main__.py) to a package layout:
  inventory/__main__.py contains the original implementation.

We re-export the public API so existing imports keep working.
"""

from __future__ import annotations

from . import __main__ as _main

__all__ = getattr(_main, "__all__", [n for n in dir(_main) if not n.startswith("_")])  # noqa: PLE0605
globals().update({name: getattr(_main, name) for name in __all__})
