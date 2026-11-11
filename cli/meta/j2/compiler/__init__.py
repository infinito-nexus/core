"""Compatibility wrapper.

This package was migrated from a flat module (compiler.py) to a package layout:
  compiler/__main__.py contains the original implementation.

We re-export the public API so existing imports keep working.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]

from utils.reexport import public_names  # noqa: E402

from . import __main__ as _main  # noqa: E402

__all__ = public_names(_main)  # noqa: PLE0605
globals().update({name: getattr(_main, name) for name in __all__})
