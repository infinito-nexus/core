"""Which role names a user holds on one application.

Most role names are global: ``roles: [administrator]`` means administrator
everywhere it is declared. ``APPLICATION_SCOPED_ROLES`` are the exception.
Those carry a distinct grant per application, so reading them from the
unscoped list would hand a user every deployed application's copy at once.
They come only from ``application_roles``::

    users:
      alice:
        application_roles:
          web-app-baserow: [mcp]

This module is the single source of truth for that rule. The Keycloak realm
group builder, the LDAP role entry builder and the Open WebUI group reconciler
all resolve membership through it, so the three paths cannot drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

MCP_READER_ROLE = "mcp-reader"
MCP_WRITER_ROLE = "mcp-writer"
MCP_LEGACY_ROLE = "mcp"

MCP_ROLES = (MCP_READER_ROLE, MCP_WRITER_ROLE)

APPLICATION_SCOPED_ROLES = frozenset({MCP_LEGACY_ROLE, *MCP_ROLES})


def expand_mcp_role(role_name: str) -> str:
    """Return the role a grant confers, resolving the pre-split name.

    Args:
        role_name: a role as written in a user's grants.
    """
    return MCP_READER_ROLE if role_name == MCP_LEGACY_ROLE else role_name


def granted_roles(user_config: Mapping[str, object], application_id: str) -> set[str]:
    """Return the role names this user holds on one application.

    Args:
        user_config: the user's merged configuration.
        application_id: the application whose grants are being resolved.
    """
    scoped = (user_config.get("application_roles") or {}).get(application_id) or []
    unscoped = [
        role
        for role in (user_config.get("roles") or [])
        if role not in APPLICATION_SCOPED_ROLES
    ]
    return set(unscoped) | set(scoped) | {expand_mcp_role(r) for r in scoped}


def members_with_role(
    users: Mapping[str, Mapping[str, object]] | None,
    application_id: str,
    role_name: str,
) -> list[str]:
    """Return the usernames holding ``role_name`` on ``application_id``.

    Args:
        users: the merged users mapping.
        application_id: the application whose grants are being resolved.
        role_name: the role to filter by.
    """
    members = []
    for username, user_config in (users or {}).items():
        cfg = user_config or {}
        if role_name in granted_roles(cfg, application_id):
            members.append(str(cfg.get("username", username)))
    return sorted(members)
