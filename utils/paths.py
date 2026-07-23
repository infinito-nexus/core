"""Filesystem SPOT for the Python side, read from group_vars/all/05_paths.yml.

``group_vars/all/05_paths.yml`` is the single source of truth for host paths.
The env layer (utils/env/handlers, exported by scripts/meta/env/load.sh) derives
the ``INFINITO_*`` env keys from it; a set env wins so callers can override.
When a tool runs outside that layer, e.g. a bare ``subprocess`` that does not
inherit the env build, the value is read straight from the group_vars SPOT, so
there is still no hardcoded literal default.

The SPOT is parsed with a plain-string line parser instead of PyYAML: the env
build runs during bootstrap (make install-system-python) before any Python
dependency exists, so this module must stay stdlib-only. Only plain
``KEY: "value"`` entries can be read this way; a Jinja expression or a missing
key is a hard error.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

_GROUP_PATHS_FILE = str(PROJECT_ROOT / "group_vars" / "all" / "05_paths.yml")
_ENTRY_RE = re.compile(
    r'^(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*"?(?P<value>[^"#]*)"?\s*(?:#.*)?$'
)


def read_group_path(key: str) -> str:
    """Plain-string path value from the group_vars paths SPOT.

    Args:
        key: top-level variable name in group_vars/all/05_paths.yml.

    Returns:
        The literal string value.

    Raises:
        KeyError: the key is not defined in the SPOT.
        ValueError: the value is not a plain string (e.g. a Jinja template).
    """
    for line in read_text(_GROUP_PATHS_FILE).splitlines():
        match = _ENTRY_RE.match(line.strip())
        if not match or match.group("key") != key:
            continue
        value = match.group("value").strip()
        if not value or "{{" in value:
            raise ValueError(
                f"{key} in {_GROUP_PATHS_FILE} must be a plain string, "
                f"got: {line.strip()!r}"
            )
        return value
    raise KeyError(f"{key} not defined in {_GROUP_PATHS_FILE}")


def _dir_var_lib() -> str:
    env = os.environ.get("INFINITO_DIR_VAR_LIB")
    if env:
        return env
    return read_group_path("DIR_VAR_LIB")


DIR_VAR_LIB = Path(_dir_var_lib())
DIR_BACKUPS = DIR_VAR_LIB / "backup"
DIR_SECRETS = DIR_VAR_LIB / "secrets"
FILE_TOKENS = DIR_SECRETS / "tokens.yml"
FILE_DATABASE_SECRETS = DIR_SECRETS / "databases.csv"
