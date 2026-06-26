"""Filesystem SPOT for the Python side, mirroring group_vars/all/05_paths.yml.

Reads the ``INFINITO_DIR_VAR_LIB`` env SPOT (default.env / the env build).
The env layer (scripts/meta/env/load.sh, sourced via BASH_ENV by every Make
recipe and by deploys) always provides it, so there is no literal fallback."""

from __future__ import annotations

import os
from pathlib import Path

DIR_VAR_LIB = Path(os.environ["INFINITO_DIR_VAR_LIB"])
DIR_SECRETS = DIR_VAR_LIB / "secrets"
FILE_TOKENS = DIR_SECRETS / "tokens.yml"
FILE_DATABASE_SECRETS = DIR_SECRETS / "databases.csv"
