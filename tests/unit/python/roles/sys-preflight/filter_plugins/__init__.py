"""Loads the filter plugins sys-preflight ships.

Ansible finds a role's ``filter_plugins/`` through the role, which puts them
outside the import path the test session runs with.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[6]
PLUGIN_DIR: Path = PROJECT_ROOT / "roles" / "sys-preflight" / "filter_plugins"


def load_plugin(name: str):
    """Load one filter plugin of the role by path.

    Args:
        name: the plugin's file name without ``.py``.

    Returns:
        The module, executed under the name ``sys_preflight_<name>``.
    """
    spec = importlib.util.spec_from_file_location(
        f"sys_preflight_{name}", PLUGIN_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
