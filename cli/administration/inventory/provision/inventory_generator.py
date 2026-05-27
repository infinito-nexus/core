from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from .subprocess_runner import run_subprocess
from .yaml_io import load_yaml

if TYPE_CHECKING:
    from pathlib import Path


def generate_dynamic_inventory(
    host: str,
    roles_dir: Path,
    categories_file: Path,
    tmp_inventory: Path,
    project_root: Path,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    """
    Generate a dynamic inventory by executing the generator as a module:
        python -m cli.administration.inventory.devices ...

    This avoids fragile file path construction and fixes 'cli/cli/...' issues.
    """
    cmd = [
        sys.executable,
        "-m",
        "cli.administration.inventory.devices",
        "--host",
        host,
        "--format",
        "yaml",
        "--inventory-style",
        "group",
        "-o",
        str(tmp_inventory),
    ]
    run_subprocess(cmd, capture_output=False, env=env)
    data = load_yaml(tmp_inventory)
    tmp_inventory.unlink(missing_ok=True)
    return data
