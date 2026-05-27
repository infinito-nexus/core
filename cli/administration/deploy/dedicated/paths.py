from __future__ import annotations

from . import PROJECT_ROOT

CLI_ROOT: str = str(PROJECT_ROOT / "cli")
PLAYBOOK_PATH: str = str(PROJECT_ROOT / "playbook.yml")
MODES_FILE: str = str(PROJECT_ROOT / "group_vars" / "all" / "01_modes.yml")
INVENTORY_VALIDATOR_PATH: str = str(
    PROJECT_ROOT / "cli" / "administration" / "inventory" / "validate" / "__main__.py"
)
