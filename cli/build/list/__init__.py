"""Compatibility wrapper.

The implementation lives in ``cli/build/list/__main__.py``; this package
re-exports its public API so ``from cli.build.list import ...`` works.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

# `__main__` does `from . import PROJECT_ROOT` at import time, so the
# constant has to be defined first.
from . import __main__ as _main  # noqa: E402

__all__ = getattr(_main, "__all__", [n for n in dir(_main) if not n.startswith("_")])  # noqa: PLE0605
globals().update({name: getattr(_main, name) for name in __all__})
