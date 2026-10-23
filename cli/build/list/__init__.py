"""Compatibility wrapper.

The implementation lives in ``cli/build/list/__main__.py``; this package
re-exports its public API so ``from cli.build.list import ...`` works.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

from utils.reexport import public_names  # noqa: E402

from . import __main__ as _main  # noqa: E402

__all__ = public_names(_main)  # noqa: PLE0605
globals().update({name: getattr(_main, name) for name in __all__})
