"""Loads the assistant package, which ships under the role's files/python/."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[7]
PACKAGE_PARENT = str(PROJECT_ROOT / "roles" / "web-svc-assistant" / "files" / "python")
if PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, PACKAGE_PARENT)


def load(name: str):
    """Return the module ``assistant.<name>``.

    Args:
        name: the module name inside the package.
    """
    return importlib.import_module(f"assistant.{name}")
