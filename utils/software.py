"""The software's own repository, read from its group_vars SPOT."""

from __future__ import annotations

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

SOFTWARE_VARS = PROJECT_ROOT / "group_vars" / "all" / "00_general.yml"
SOFTWARE_REPOSITORY: str = load_yaml(str(SOFTWARE_VARS))["SOFTWARE_REPOSITORY"]
