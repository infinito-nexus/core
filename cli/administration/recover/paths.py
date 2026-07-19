"""Standard filesystem layout the recover console restores into.

Derived from the paths SPOT (utils.paths, backed by
group_vars/all/05_paths.yml). This uniform layout is what lets a recovery
target a host by name alone: every host restores into these same paths.
"""

from __future__ import annotations

from pathlib import Path

from utils.paths import DIR_BACKUPS as _DIR_BACKUPS
from utils.paths import DIR_SECRETS as _DIR_SECRETS
from utils.paths import DIR_VAR_LIB as _DIR_VAR_LIB
from utils.storage.nfs import STATE_SUBDIR, get_export_base, state_path

DIR_VAR_LIB = str(_DIR_VAR_LIB)
BACKUP_ROOT = str(_DIR_BACKUPS)
SECRETS_DIR = str(_DIR_SECRETS)
NFS_EXPORT_STATE = state_path(get_export_base(), STATE_SUBDIR)
RECOVER_MOUNT = "/mnt/infinito-recover"


def volume_from_source(source: str) -> str:
    """Docker volume name embedded in a snapshot path ``<generation>/<volume>/files``."""
    path = Path(source.rstrip("/"))
    return path.parent.name if path.name == "files" else path.name
