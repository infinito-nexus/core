"""
Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: the platform realm.
    KC_WORKSPACES_CLIENT: clientId of the client holding the ``<id>:<role>`` roles.
    WORKSPACE: the workspace id, a lowercase UUID.
    WORKSPACE_ACTION: ``apply`` creates the marked organization of WORKSPACE with its
        five role groups, client roles and mappings; ``destroy`` deletes the client
        roles, then the organization with its groups.

Output: one ``<outcome> <kind> <name>`` line per organization, group, client role
and mapping, for ``apply`` then ``owner_group <id>``, the Keycloak id of the
organization's ``Owner`` group, then one ``summary`` line; ``failed <error>`` on
a failure.
Exit: 0 converged, 1 otherwise.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
from pathlib import Path

from keycloak_admin import (
    Keycloak,
    KeycloakError,
    KeycloakHTTPError,
    container_credentials,
)

WORKSPACE_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
MARKER = "workspace.id"
ALIAS_PREFIX = "ws-"
OWNER = "Owner"
ROLES = (OWNER, "Admin", "Operator", "Billing", "Viewer")
OWNER_LINE = "owner_group"
ACTIONS = ("apply", "destroy")
OUTCOMES = ("created", "deleted", "unchanged", "gone")
ERRORS = (KeycloakError, OSError, KeyError, TypeError, ValueError)
NOT_FOUND = 404
GROUP_PAGE = 100


class AmbiguousError(KeycloakError):
    pass


def validate(workspace: str) -> str:
    """
    Args:
        workspace: the workspace id the store chose.

    Returns:
        ``workspace``; a value that is not a lowercase UUID raises ValueError.
    """
    if not WORKSPACE_ID.match(workspace or ""):
        raise ValueError("WORKSPACE is not a lowercase UUID")
    return workspace


def alias(workspace: str) -> str:
    """
    Args:
        workspace: the workspace id.

    Returns:
        The name and alias of the workspace's organization.
    """
    return f"{ALIAS_PREFIX}{workspace}"


def role_name(workspace: str, role: str) -> str:
    """
    Args:
        workspace: the workspace id.
        role: one of ROLES.

    Returns:
        The client role ``<id>:<role>``.
    """
    return f"{workspace}:{role}"


def find(kc: Keycloak, workspace: str) -> dict | None:
    """
    Args:
        kc: client.
        workspace: the workspace id.

    Returns:
        The one organization whose marker attribute holds ``workspace``, or None;
        two such organizations raise AmbiguousError.
    """
    query = urllib.parse.urlencode(
        {
            "q": f"{MARKER}:{workspace}",
            "briefRepresentation": "false",
            "first": 0,
            "max": 2,
        }
    )
    found, _ = kc.call("GET", f"organizations?{query}")
    marked = [
        org
        for org in found
        if workspace in (org.get("attributes") or {}).get(MARKER, [])
    ]
    if len(marked) > 1:
        raise AmbiguousError(
            f"{len(marked)} organizations carry the marker of {workspace}"
        )
    return marked[0] if marked else None


def groups(kc: Keycloak, org_id: str) -> dict[str, dict]:
    """
    Args:
        kc: client.
        org_id: the organization.

    Returns:
        Its top-level groups by name, each with its role mappings.
    """
    query = urllib.parse.urlencode(
        {"briefRepresentation": "false", "first": 0, "max": GROUP_PAGE}
    )
    found, _ = kc.call("GET", f"organizations/{org_id}/groups?{query}")
    return {group["name"]: group for group in found}


def client_uuid(kc: Keycloak, client_id: str) -> str:
    """
    Args:
        kc: client.
        client_id: the clientId.

    Returns:
        The internal id of that client; a realm without it raises KeycloakError.
    """
    query = urllib.parse.urlencode({"clientId": client_id, "search": "false"})
    found, _ = kc.call("GET", f"clients?{query}")
    for client in found:
        if client["clientId"] == client_id:
            return client["id"]
    raise KeycloakError(f"the realm has no client {client_id}")


def role_path(uuid: str, name: str) -> str:
    """
    Args:
        uuid: internal id of the client.
        name: the client role.

    Returns:
        The admin path of that client role.
    """
    return f"clients/{uuid}/roles/{urllib.parse.quote(name, safe='')}"


def client_role(kc: Keycloak, uuid: str, name: str) -> dict | None:
    """
    Args:
        kc: client.
        uuid: internal id of the client.
        name: the role name.

    Returns:
        The client role, or None when it is absent.
    """
    try:
        found, _ = kc.call("GET", role_path(uuid, name))
    except KeycloakHTTPError as error:
        if error.status == NOT_FOUND:
            return None
        raise
    return found


def ensure_organization(kc: Keycloak, workspace: str) -> tuple[dict, str]:
    """
    Args:
        kc: client.
        workspace: the workspace id.

    Returns:
        The marked organization and ``created`` or ``unchanged``. The create
        request alone carries the marker; an alias held by an unmarked
        organization answers 409, which raises.
    """
    org = find(kc, workspace)
    if org is not None:
        return org, "unchanged"
    kc.call(
        "POST",
        "organizations",
        {
            "name": alias(workspace),
            "alias": alias(workspace),
            "enabled": True,
            "attributes": {MARKER: [workspace]},
        },
    )
    org = find(kc, workspace)
    if org is None:
        raise KeycloakError(f"the organization {alias(workspace)} carries no marker")
    return org, "created"


def ensure_groups(kc: Keycloak, org_id: str) -> tuple[dict[str, dict], list[str]]:
    """
    Args:
        kc: client.
        org_id: the organization.

    Returns:
        The role groups by name after creating the missing ones, and one line per group.
    """
    held = groups(kc, org_id)
    lines = []
    for role in ROLES:
        if role in held:
            lines.append(f"unchanged group {role}")
            continue
        kc.call("POST", f"organizations/{org_id}/groups", {"name": role})
        lines.append(f"created group {role}")
    return groups(kc, org_id), lines


def ensure_roles(kc: Keycloak, uuid: str, workspace: str) -> tuple[dict, list[str]]:
    """
    Args:
        kc: client.
        uuid: internal id of the workspaces client.
        workspace: the workspace id.

    Returns:
        The client roles by role after creating the missing ones, and one line per role.
    """
    roles: dict[str, dict] = {}
    lines = []
    for role in ROLES:
        name = role_name(workspace, role)
        found = client_role(kc, uuid, name)
        outcome = "unchanged"
        if found is None:
            kc.call("POST", f"clients/{uuid}/roles", {"name": name})
            found = client_role(kc, uuid, name)
            outcome = "created"
        if found is None:
            raise KeycloakError(f"the client role {name} was not created")
        roles[role] = found
        lines.append(f"{outcome} role {name}")
    return roles, lines


def ensure_mappings(
    kc: Keycloak, org_id: str, client: str, uuid: str, held: dict, roles: dict
) -> list[str]:
    """
    Args:
        kc: client.
        org_id: the organization.
        client: clientId of the workspaces client.
        uuid: its internal id.
        held: the role groups by name, with their role mappings.
        roles: the client roles by role.

    Returns:
        One line per role group, mapped onto its client role.
    """
    lines = []
    for role in ROLES:
        group = held[role]
        mapped = (group.get("clientRoles") or {}).get(client, [])
        if roles[role]["name"] in mapped:
            lines.append(f"unchanged mapping {role}")
            continue
        kc.call(
            "POST",
            f"organizations/{org_id}/groups/{group['id']}/role-mappings/clients/{uuid}",
            [{"id": roles[role]["id"], "name": roles[role]["name"]}],
        )
        lines.append(f"created mapping {role}")
    return lines


def apply(kc: Keycloak, workspace: str, client: str) -> list[str]:
    """
    Args:
        kc: client.
        workspace: the workspace id.
        client: clientId of the workspaces client.

    Returns:
        One line per organization, group, client role and mapping it converged.
    """
    org, outcome = ensure_organization(kc, workspace)
    lines = [f"{outcome} organization {alias(workspace)}"]
    held, group_lines = ensure_groups(kc, org["id"])
    uuid = client_uuid(kc, client)
    roles, role_lines = ensure_roles(kc, uuid, workspace)
    mapping_lines = ensure_mappings(kc, org["id"], client, uuid, held, roles)
    return lines + group_lines + role_lines + mapping_lines


def owner_group(kc: Keycloak, workspace: str) -> str:
    """
    Args:
        kc: client.
        workspace: the workspace id.

    Returns:
        The id of the top-level ``Owner`` group of the organization that carries
        the marker of ``workspace``; an absent organization or group raises
        KeycloakError.
    """
    org = find(kc, workspace)
    if org is None:
        raise KeycloakError(f"no organization carries the marker of {workspace}")
    held = groups(kc, org["id"])
    if OWNER not in held:
        raise KeycloakError(f"the organization {alias(workspace)} has no {OWNER} group")
    return held[OWNER]["id"]


def delete(kc: Keycloak, path: str) -> str:
    """
    Args:
        kc: client.
        path: path below ``/admin/realms/<realm>/``.

    Returns:
        ``deleted``, or ``gone`` when the resource was already absent.
    """
    try:
        kc.call("DELETE", path)
    except KeycloakHTTPError as error:
        if error.status == NOT_FOUND:
            return "gone"
        raise
    return "deleted"


def destroy(kc: Keycloak, workspace: str, client: str) -> list[str]:
    """
    Args:
        kc: client.
        workspace: the workspace id.
        client: clientId of the workspaces client.

    Returns:
        One line per client role, then one for the organization, which goes last.
    """
    org = find(kc, workspace)
    uuid = client_uuid(kc, client)
    lines = [
        f"{delete(kc, role_path(uuid, role_name(workspace, role)))} role "
        f"{role_name(workspace, role)}"
        for role in ROLES
    ]
    if org is None:
        return [*lines, f"gone organization {alias(workspace)}"]
    outcome = delete(kc, f"organizations/{org['id']}")
    return [*lines, f"{outcome} organization {alias(workspace)}"]


def main() -> int:
    env = os.environ
    try:
        workspace = validate(env["WORKSPACE"])
        action = env["WORKSPACE_ACTION"]
        if action not in ACTIONS:
            raise ValueError("WORKSPACE_ACTION is neither apply nor destroy")
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        run = apply if action == "apply" else destroy
        lines = run(kc, workspace, env["KC_WORKSPACES_CLIENT"])
        if action == "apply":
            lines.append(f"{OWNER_LINE} {owner_group(kc, workspace)}")
    except ERRORS as error:
        print(f"failed {error}")
        return 1
    for line in lines:
        print(line)
    outcomes = [line.split(" ", 1)[0] for line in lines]
    print("summary " + " ".join(f"{key}={outcomes.count(key)}" for key in OUTCOMES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
