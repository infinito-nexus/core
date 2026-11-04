"""Public names of a module, for the package shims that re-export one."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def public_names(module: ModuleType) -> list[str]:
    """Return the names ``module`` defines itself, honouring its ``__all__``.

    Listing ``dir()`` instead sweeps in whatever the module imported, so every
    shim re-exported ``Path`` and ``Any``. Sphinx then found the same python
    target in nine packages and reported 320 ambiguous cross-references.

    Args:
        module: the module whose public API is being re-exported.
    """
    declared = getattr(module, "__all__", None)
    if declared is not None:
        return list(declared)
    return [
        name
        for name in dir(module)
        if not name.startswith("_")
        and getattr(getattr(module, name), "__module__", module.__name__)
        == module.__name__
    ]
