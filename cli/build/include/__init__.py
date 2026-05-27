"""Compatibility wrapper.

The implementation lives in ``cli/build/include/__main__.py``; this package
re-exports its public API so ``from cli.build.include import ...`` works.
"""

from __future__ import annotations

from . import __main__ as _main
__all__ = getattr(_main, "__all__", [n for n in dir(_main) if not n.startswith("_")])
globals().update({name: getattr(_main, name) for name in __all__})

# Prefer explicit __all__ if the original module defined it.
__all__ = getattr(_main, "__all__", [n for n in dir(_main) if not n.startswith("_")])
