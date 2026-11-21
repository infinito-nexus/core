"""Resolve the email policy of the platform realm.

``mailbox``: every user's primary address is ``<username>@<DOMAIN_PRIMARY>``
and the address the user brings is the secondary one. ``external``: the
address the user brings is the primary one. The inventory records the policy;
without an entry it is ``external``, the default of
``roles/web-app-keycloak/meta/services.yml``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from utils.mail.provider import provider_deployed

if TYPE_CHECKING:
    from pathlib import Path

POLICY_MAILBOX = "mailbox"
POLICY_EXTERNAL = "external"
POLICIES = (POLICY_MAILBOX, POLICY_EXTERNAL)
POLICY_APPLICATION = "web-app-keycloak"
POLICY_PATH = ("services", "keycloak", "email", "policy")
DIRECTORY_ROLE = "svc-db-openldap"


def default_policy(variables: Mapping[str, Any], roles_dir: Path) -> str:
    """The policy a new inventory records.

    Args:
        variables: the play's variable scope, read for a rendered
            ``MAIL_PROVIDER``, ``applications`` and ``groups``.
        roles_dir: repository ``roles/`` directory.

    Returns:
        ``mailbox`` when ``web-app-keycloak``, which keeps each user's former
        address as the secondary one, the mail provider and ``svc-db-openldap``,
        which stores the mailbox addresses, all have a host anywhere in the
        inventory; ``external`` otherwise.
    """
    groups = variables.get("groups") or {}
    if (
        groups.get(POLICY_APPLICATION)
        and groups.get(DIRECTORY_ROLE)
        and provider_deployed(variables, roles_dir)
    ):
        return POLICY_MAILBOX
    return POLICY_EXTERNAL


def resolve_policy(application_overrides: Mapping[str, Any]) -> str:
    """The policy the inventory records, ``external`` without an entry.

    Args:
        application_overrides: the inventory ``applications`` mapping.

    Raises:
        ValueError: the inventory sets a value outside ``POLICIES``.
    """
    node: Any = application_overrides.get(POLICY_APPLICATION)
    for key in POLICY_PATH:
        if not isinstance(node, Mapping) or key not in node:
            return POLICY_EXTERNAL
        node = node[key]
    value = str(node).strip()
    if value not in POLICIES:
        raise ValueError(
            f"applications.{POLICY_APPLICATION}.{'.'.join(POLICY_PATH)} is "
            f"{value!r}; it must be one of {', '.join(POLICIES)} written literally."
        )
    return value
