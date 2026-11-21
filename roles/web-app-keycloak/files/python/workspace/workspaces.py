"""
Exports:
    RefusalError: a request core refuses for good; ``reason`` names it in the refusal line.
    Workspace: the members, role groups and pending entries of one marked organization.
    service_account: the ``workspace-members`` client signed in from the environment.
    rbac_groups: the platform RBAC groups a user holds.
    rbac_member: whether a user holds a platform RBAC group.
    marked_workspaces: the workspaces whose organizations a user is a member of.
    refusal_line: the last output line of a refusal.
    write_private: a file only the task's own user reads.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from keycloak_admin import KeycloakError, ServiceAccount
from organization import MARKER, ROLES, WORKSPACE_ID, find, groups

PENDING_PREFIX = "workspace.pending."
INVITE_PREFIX = "workspace.invite."
KEYCLOAK_ID = WORKSPACE_ID
PAGE = 100


class RefusalError(Exception):
    """
    Args:
        reason: one of the refusal reasons of the members and user templates.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def refusal_line(key: str, value: str, reason: str) -> str:
    """
    Args:
        key: ``workspace`` or ``user``.
        value: the workspace id or the user id.
        reason: the refusal reason.

    Returns:
        The JSON object a refused task prints as its last output line.
    """
    return json.dumps({key: value, "refused": reason}, separators=(",", ":"))


def service_account(env: dict) -> ServiceAccount:
    """
    Args:
        env: the task environment with KC_URL, KC_REALM, KC_CLIENT_ID and
            KC_CLIENT_SECRET_FILE, the file holding the client secret.

    Returns:
        A client signed in by the client-credentials grant of that client.
    """
    secret = Path(env["KC_CLIENT_SECRET_FILE"]).read_text(encoding="utf-8").strip()
    return ServiceAccount(env["KC_URL"], env["KC_REALM"], env["KC_CLIENT_ID"], secret)


def keycloak_id(value: str, name: str) -> str:
    """
    Args:
        value: the value of one task variable.
        name: the variable, named in the error.

    Returns:
        ``value`` when it has the form of a Keycloak id; otherwise ValueError.
    """
    if not KEYCLOAK_ID.match(value or ""):
        raise ValueError(f"{name} is not a Keycloak id")
    return value


def paged(kc: ServiceAccount, path: str) -> list[dict]:
    """
    Args:
        kc: client.
        path: a listing path below the realm, without paging parameters.

    Returns:
        Every entry of the listing, page by page.
    """
    found: list[dict] = []
    while True:
        query = urllib.parse.urlencode(
            {"first": len(found), "max": PAGE, "briefRepresentation": "false"}
        )
        page, _ = kc.call("GET", f"{path}?{query}")
        found.extend(page)
        if len(page) < PAGE:
            return found


def rbac_groups(kc: ServiceAccount, user_id: str, root: str) -> list[dict]:
    """
    Args:
        kc: client.
        user_id: the user.
        root: path of the RBAC group root, such as ``/roles``.

    Returns:
        The groups below the RBAC root the user is in, each with ``id`` and ``path``.
    """
    prefix = root.rstrip("/") + "/"
    held, _ = kc.call("GET", f"users/{user_id}/groups?briefRepresentation=true")
    return [group for group in held if group.get("path", "").startswith(prefix)]


def rbac_member(kc: ServiceAccount, user_id: str, root: str) -> bool:
    """
    Args:
        kc: client.
        user_id: the user.
        root: path of the RBAC group root, such as ``/roles``.

    Returns:
        True when the user is in a group below the RBAC root.
    """
    return bool(rbac_groups(kc, user_id, root))


def marked_workspaces(kc: ServiceAccount, user_id: str) -> set[str]:
    """
    Args:
        kc: client.
        user_id: the user.

    Returns:
        The workspace ids of every organization with a workspace marker the
        user is a member of.
    """
    query = urllib.parse.urlencode({"briefRepresentation": "false"})
    found, _ = kc.call("GET", f"organizations/members/{user_id}/organizations?{query}")
    return {
        workspace
        for org in found
        for workspace in (org.get("attributes") or {}).get(MARKER, [])
    }


def write_private(path: str, payload: object) -> None:
    """
    Args:
        path: file to write, created or truncated with mode 0600.
        payload: JSON value written into it.
    """
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(payload, stream)


@dataclass
class Workspace:
    """
    Args:
        workspace: the workspace id.
        action: the task's action, named in every change line.
        org: the organization as Keycloak holds it, attributes included.
        members: its members by user id.
        role_groups: its role groups by role.
        holders: the user ids of each role group.
    """

    workspace: str
    action: str
    org: dict
    members: dict[str, dict]
    role_groups: dict[str, dict]
    holders: dict[str, set[str]]

    @classmethod
    def load(cls, kc: ServiceAccount, workspace: str, action: str) -> Workspace | None:
        """
        Args:
            kc: client.
            workspace: the workspace id.
            action: the task's action.

        Returns:
            The workspace of the one marked organization, or None when none carries the marker.
        """
        org = find(kc, workspace)
        if org is None:
            return None
        base = f"organizations/{org['id']}"
        held = groups(kc, org["id"])
        missing = [role for role in ROLES if role not in held]
        if missing:
            raise KeycloakError(f"the organization lacks the role groups {missing}")
        return cls(
            workspace=workspace,
            action=action,
            org=org,
            members={m["id"]: m for m in paged(kc, f"{base}/members")},
            role_groups={role: held[role] for role in ROLES},
            holders={
                role: {
                    m["id"]
                    for m in paged(kc, f"{base}/groups/{held[role]['id']}/members")
                }
                for role in ROLES
            },
        )

    @property
    def base(self) -> str:
        """
        Returns:
            The admin path of the organization.
        """
        return f"organizations/{self.org['id']}"

    def roles_of(self, user_id: str) -> list[str]:
        """
        Args:
            user_id: a member.

        Returns:
            The role groups the member is in, in the order of ROLES.
        """
        return [role for role in ROLES if user_id in self.holders[role]]

    def entries(self) -> dict[str, dict[str, str]]:
        """
        Returns:
            Each pending invitation key with its role and address, from the
            ``workspace.pending.<role>`` and ``workspace.invite.<key>`` attributes.
        """
        attributes = self.org.get("attributes") or {}
        found = {}
        for role in ROLES:
            for key in attributes.get(PENDING_PREFIX + role, []):
                address = attributes.get(INVITE_PREFIX + key, [])
                if address:
                    found[key] = {"role": role, "address": address[0]}
        return found

    def owners_after(self, user_id: str, roles: list[str]) -> int:
        """
        Args:
            user_id: the member a change concerns.
            roles: the role groups that member holds after the change.

        Returns:
            How many enabled members hold Owner after the change.
        """
        count = 0
        for member_id, member in self.members.items():
            held = roles if member_id == user_id else self.roles_of(member_id)
            if "Owner" in held and member.get("enabled") is True:
                count += 1
        return count

    def line(self) -> str:
        """
        Returns:
            The membership line: every member's id, role groups and enabled flag,
            and every pending key with its role; no name, username or address.
        """
        members = [
            {
                "id": member_id,
                "groups": self.roles_of(member_id),
                "enabled": self.members[member_id].get("enabled") is True,
            }
            for member_id in sorted(self.members)
        ]
        pending = [
            {"key": key, "role": entry["role"]}
            for key, entry in sorted(self.entries().items())
        ]
        return json.dumps(
            {"workspace": self.workspace, "members": members, "pending": pending},
            separators=(",", ":"),
        )

    def roster(self) -> dict:
        """
        Returns:
            Each member's id, username, email, verified flag, role groups and
            enabled flag, for the Semaphore mirror only.
        """
        return {
            "workspace": self.workspace,
            "members": [
                {
                    "id": member_id,
                    "username": member.get("username"),
                    "email": member.get("email"),
                    "emailVerified": member.get("emailVerified") is True,
                    "enabled": member.get("enabled") is True,
                    "groups": self.roles_of(member_id),
                }
                for member_id, member in sorted(self.members.items())
            ],
        }
