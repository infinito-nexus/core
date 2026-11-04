"""Loads the lookup plugins sys-preflight ships.

Ansible finds a role's ``lookup_plugins/`` through the role, which puts them
outside the import path the test session runs with.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[6]
PLUGIN_DIR: Path = PROJECT_ROOT / "roles" / "sys-preflight" / "lookup_plugins"


def load_plugin(name: str):
    """Load one lookup plugin of the role by path.

    Args:
        name: the plugin's file name without ``.py``.

    Returns:
        The module, registered in ``sys.modules`` as ``sys_preflight_<name>``
        so ``mock.patch`` reaches its attributes by that name.
    """
    spec = importlib.util.spec_from_file_location(
        f"sys_preflight_{name}", PLUGIN_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
