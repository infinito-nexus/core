from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

MAIL_WRAPPER = "web-app-email"
MAIL_SERVICE_KEY = "email"
PROVIDER_KEY = "provider"


def default_provider(roles_dir: Path) -> str:
    """The provider the wrapper role ships with.

    Args:
        roles_dir: repository ``roles/`` directory.

    Returns:
        ``services.email.provider`` of the wrapper's ``meta/services.yml``.
    """
    services = load_yaml_any(
        str(roles_dir / MAIL_WRAPPER / ROLE_FILE_META_SERVICES), default_if_missing={}
    )
    return str(services[MAIL_SERVICE_KEY][PROVIDER_KEY]).strip()


def _override(applications: Mapping[str, Any] | None) -> str:
    node: Any = applications
    for key in (MAIL_WRAPPER, "services", MAIL_SERVICE_KEY, PROVIDER_KEY):
        if not isinstance(node, dict) or key not in node:
            return ""
        node = node[key]
    return str(node).strip() if isinstance(node, str) else ""


def configured_provider(applications: Mapping[str, Any] | None, roles_dir: Path) -> str:
    """The provider the wrapper selects for this inventory.

    Args:
        applications: the inventory's ``applications`` variable.
        roles_dir: repository ``roles/`` directory.

    Returns:
        The inventory's ``applications.web-app-email.services.email.provider``
        when it names a role, else :func:`default_provider`.
    """
    return _override(applications) or default_provider(roles_dir)


def provider_roles(roles_dir: Path) -> list[str]:
    """Every role the wrapper can dispatch to, in fallback priority order.

    Args:
        roles_dir: repository ``roles/`` directory.

    Returns:
        :func:`default_provider` first, then every role whose primary entity
        ``covers`` the ``email`` key, without duplicates.
    """
    ordered = [default_provider(roles_dir)]
    for entry in build_service_registry_from_roles_dir(roles_dir).values():
        role = entry.get("role")
        if (
            "canonical" not in entry
            and MAIL_SERVICE_KEY in (entry.get("covers") or [])
            and role not in ordered
        ):
            ordered.append(role)
    return ordered


def deployed_roles(groups: dict[str, Any] | None) -> list[str]:
    """Roles with at least one host anywhere in the inventory.

    Args:
        groups: Ansible's ``groups`` mapping of group name to member hosts.

    Returns:
        Group names that have members.
    """
    return [name for name, hosts in (groups or {}).items() if hosts]


def resolve_active_provider(
    configured: str, deployed: list[str] | tuple[str, ...], roles_dir: Path
) -> str:
    """The role acting as mail provider for this deploy.

    Args:
        configured: the provider :func:`configured_provider` selects.
        deployed: roles present cluster-wide, from :func:`deployed_roles`.
        roles_dir: repository ``roles/`` directory.

    Returns:
        ``configured`` when that role is deployed, otherwise the
        highest-priority :func:`provider_roles` entry that is; ``configured``
        when none is.
    """
    present = set(deployed or ())
    if configured and configured in present:
        return configured

    for role in provider_roles(roles_dir):
        if role in present:
            return role

    return configured


def active_provider(variables: Mapping[str, Any], roles_dir: Path) -> str:
    """The mail provider role of a play.

    Args:
        variables: the play's variable scope, read for a rendered
            ``MAIL_PROVIDER``, ``applications`` and ``groups``.
        roles_dir: repository ``roles/`` directory.

    Returns:
        The role :func:`resolve_active_provider` picks for ``MAIL_PROVIDER``,
        or for the provider :func:`configured_provider` selects when it is empty.
    """
    value = variables.get("MAIL_PROVIDER")
    configured = (
        str(value).strip()
        if value
        else configured_provider(variables.get("applications"), roles_dir)
    )
    return resolve_active_provider(
        configured, deployed_roles(variables.get("groups")), roles_dir
    )


def provider_deployed(variables: Mapping[str, Any], roles_dir: Path) -> bool:
    """True when the active mail provider has a host anywhere in the inventory.

    Args:
        variables: the play's variable scope, see :func:`active_provider`.
        roles_dir: repository ``roles/`` directory.
    """
    groups = variables.get("groups") or {}
    if not deployed_roles(groups):
        return False
    return bool(groups.get(active_provider(variables, roles_dir)))
