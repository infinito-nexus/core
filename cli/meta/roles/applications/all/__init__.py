"""Compatibility wrapper.

This package was migrated from a flat module (all.py) to a package layout:
  all/__main__.py contains the original implementation.

We re-export the public API so existing imports keep working.
"""

from __future__ import annotations

from utils.reexport import public_names

from . import __main__ as _main

__all__ = public_names(_main)  # noqa: PLE0605
globals().update({name: getattr(_main, name) for name in __all__})
