"""Agent routines: one LangGraph graph per routine.

A routine module in this package exposes:

- ``STEPS``: the ordered steps as a list of one-line strings, for an
  interactive agent to follow by hand.
- ``MERMAID``: a Mermaid ``flowchart`` of the same steps, as a string.
- ``build()``: returns the compiled LangGraph graph. Imported lazily, so
  ``show`` never needs LangGraph installed, only ``run`` does.

A routine's deterministic steps call the repository's own logic in ``cli/``
and ``utils/`` through a make target or ``python -m``; the logic stays there.
A routine never imports a skill or a role.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

__all__ = ["discover", "load"]

HELPERS = {"contract"}


def _routine_modules() -> dict[str, str]:
    """Map every routine's flat name to its dotted submodule path.

    A routine may live in a subpackage (``debug/ci.py``); the flat name joins
    the path with ``_`` (``debug_ci``), so a skill names a routine by one
    stable name wherever its file sits. Helper modules (the routine contract)
    and private modules are left out.
    """
    found: dict[str, str] = {}
    for info in pkgutil.walk_packages(__path__, prefix=f"{__name__}."):
        if info.ispkg:
            continue
        relative = info.name[len(__name__) + 1 :]
        leaf = relative.rsplit(".", 1)[-1]
        if leaf.startswith("_") or leaf in HELPERS:
            continue
        found["_".join(relative.split("."))] = relative
    return found


def discover() -> list[str]:
    """Return the flat name of every routine module in this package."""
    return sorted(_routine_modules())


def load(name: str) -> ModuleType:
    """Import and return the routine module ``name``.

    Args:
        name: the routine's flat name, as ``discover`` lists it.
    """
    modules = _routine_modules()
    if name not in modules:
        raise KeyError(name)
    return importlib.import_module(f"{__name__}.{modules[name]}")
