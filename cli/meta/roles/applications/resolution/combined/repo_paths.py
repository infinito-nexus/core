from __future__ import annotations

from typing import TYPE_CHECKING

from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def roles_dir() -> Path:
    return PROJECT_ROOT / "roles"


def role_dir(role_name: str) -> Path:
    return roles_dir() / role_name


def role_meta_path(role_name: str) -> Path:
    return role_dir(role_name) / ROLE_FILE_META_MAIN


def role_vars_path(role_name: str) -> Path:
    return role_dir(role_name) / ROLE_FILE_VARS_MAIN


def role_services_path(role_name: str) -> Path:
    """Return the services manifest path."""
    return role_dir(role_name) / ROLE_FILE_META_SERVICES


def role_config_path(role_name: str) -> Path:
    """Backwards-compatible alias that now points at meta/services.yml.

    Kept so call sites that historically asked for "config" still work; the
    contents are the services map directly (no `compose.services` wrapper).
    """
    return role_services_path(role_name)
