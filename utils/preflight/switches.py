"""Read the per-check switches of the pre-flight role outside Ansible."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from pathlib import Path

PREFLIGHT_ROLE = "sys-preflight"


def check_enabled(check: str, roles_dir: Path) -> bool:
    """Whether one pre-flight check is switched on.

    Args:
        check: the key under ``<entity>.checks`` in the role's
            ``meta/services.yml``, such as ``inventory``.
        roles_dir: the roles tree that holds the pre-flight role.

    Returns:
        The literal ``enabled`` boolean the role declares for ``check``.

    Raises:
        FileNotFoundError: ``roles_dir`` holds no pre-flight role.
        ValueError: the role declares no ``enabled`` for ``check``.
        TypeError: ``enabled`` is not a literal boolean; a Jinja expression
            cannot be rendered before Ansible starts.
    """
    path = roles_dir / PREFLIGHT_ROLE / ROLE_FILE_META_SERVICES
    services = load_yaml_any(str(path))
    entity = entity_name(PREFLIGHT_ROLE)
    try:
        enabled = services[entity]["checks"][check]["enabled"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"{path}: {entity}.checks.{check}.enabled is not declared"
        ) from exc
    if not isinstance(enabled, bool):
        raise TypeError(
            f"{path}: {entity}.checks.{check}.enabled must be true or false, "
            f"got {enabled!r}"
        )
    return enabled
