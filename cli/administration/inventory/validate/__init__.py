"""Public API of the inventory validator.

Split by concern (DRY/SPOT/KISS):
- ``keys``: dotted-path key extraction
- ``loaders``: YAML parsing + inventory directory scans
- ``applications``: applications-vs-defaults+variants validation
- ``users``: user-vs-defaults validation
- ``hosts``: ``all.children`` host-group validation
- ``__main__``: argparse + orchestration
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]

from .__main__ import main  # noqa: E402
from .applications import compare_application_keys  # noqa: E402
from .hosts import validate_host_keys  # noqa: E402
from .keys import recursive_keys  # noqa: E402
from .loaders import load_inventory_files, load_yaml_file  # noqa: E402
from .users import compare_user_keys  # noqa: E402

__all__ = [
    "PROJECT_ROOT",
    "compare_application_keys",
    "compare_user_keys",
    "load_inventory_files",
    "load_yaml_file",
    "main",
    "recursive_keys",
    "validate_host_keys",
]
