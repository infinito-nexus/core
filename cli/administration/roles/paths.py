"""Where custom roles are staged before the pull moves them under ``roles/``."""

from __future__ import annotations

from utils.cache import PROJECT_ROOT

WORK_DIR = PROJECT_ROOT / "build" / "custom-roles"
