from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_ACCOUNT, ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from pathlib import Path

POLICY_KEYS = ("username_max_length", "username_pattern", "source", "agent_reachable")


def _read(path: Path) -> object:
    return load_yaml_any(str(path), default_if_missing={}) if path.is_file() else None


def sso_roles(roles_dir: Path) -> list[str]:
    """Return the roles whose meta/services.yml enables SSO or leaves it to a variable.

    Args:
        roles_dir: the Ansible roles tree to read.
    """
    found = []
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        services = _read(role_dir / ROLE_FILE_META_SERVICES)
        sso = services.get("sso") if isinstance(services, dict) else None
        if isinstance(sso, dict) and sso.get("enabled") is not False:
            found.append(role_dir.name)
    return found


def load_policies(roles_dir: Path) -> dict[str, object]:
    """Return ``{role: account_policy}`` for every role shipping meta/account.yml.

    Args:
        roles_dir: the Ansible roles tree to read.
    """
    policies = {}
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        data = _read(role_dir / ROLE_FILE_META_ACCOUNT)
        if data is not None:
            policies[role_dir.name] = (
                data.get("account_policy") if isinstance(data, dict) else None
            )
    return policies


def username_max_length(policies: dict[str, dict]) -> int:
    """Return the human username ceiling: the smallest limit of any role.

    Args:
        policies: ``{role: account_policy}`` from ``load_policies``.
    """
    return min(policy["username_max_length"] for policy in policies.values())


def account_max_length(policies: dict[str, dict]) -> int:
    """Return the agent account ceiling: the smallest limit of an agent-reachable role.

    Args:
        policies: ``{role: account_policy}`` from ``load_policies``.
    """
    return min(
        policy["username_max_length"]
        for policy in policies.values()
        if policy["agent_reachable"]
    )


def username_patterns(policies: dict[str, dict]) -> list[str]:
    """Return every distinct username pattern, sorted.

    Args:
        policies: ``{role: account_policy}`` from ``load_policies``.
    """
    return sorted({policy["username_pattern"] for policy in policies.values()})
