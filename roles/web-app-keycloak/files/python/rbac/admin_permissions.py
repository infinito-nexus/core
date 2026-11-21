#!/usr/bin/env python3
"""Converge the fine-grained admin permissions (v2) that let approver groups grant role groups.

Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: realm holding the groups and its ``admin-permissions`` client.

Stdin: JSON object with
    prefix: name prefix of every policy and permission this script owns; an owned
        entry the approvers no longer produce is deleted.
    approvers: ``{"approver": <group path>, "groups": [<group path>, ...]}`` objects.
        Members of ``approver`` get ``view`` and ``manage-group-membership`` on every
        user and ``view`` and ``manage-membership`` on each listed group.

Output: one ``<outcome> <kind> <name>`` line per policy and permission, one
``missing group <path>`` line per group the realm lacks, then one ``summary`` line.
Exit: 0 every entry converged, 1 otherwise.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.parse
from pathlib import Path

from keycloak_admin import PAGE, Keycloak, KeycloakError, container_credentials

ADMIN_PERMISSIONS_CLIENT = "admin-permissions"
OUTCOMES = ("created", "updated", "unchanged", "deleted", "missing", "failed")
ERRORS = (KeycloakError, OSError, KeyError, TypeError, ValueError)
USER_SCOPES = ["view", "manage-group-membership"]
GROUP_SCOPES = ["view", "manage-membership"]
NOT_FOUND = "HTTP 404"
ROUTES = {"policy": "policy/group", "permission": "permission/scope"}


def fingerprint(payload: dict) -> str:
    """Return the description that marks an entry as written from ``payload``.

    Args:
        payload: the representation Keycloak receives, without its description.
    """
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"Generated from meta/rbac.yml by web-app-keycloak; digest {digest[:16]}"


def desired(
    prefix: str, approver: str, approver_id: str, group_ids: list[str]
) -> list[tuple[str, dict]]:
    """Return the ``(kind, representation)`` pairs one approver group needs.

    Args:
        prefix: name prefix of every owned entry.
        approver: path of the approver group.
        approver_id: its Keycloak id.
        group_ids: ids of the groups its members may grant; none leaves out the
            group permission.

    Returns:
        The group policy first, then its permissions, which name the policy in
        ``policies`` by name.
    """
    policy = f"{prefix}:{approver}"
    common = {"logic": "POSITIVE", "decisionStrategy": "UNANIMOUS"}
    entries = [
        (
            "policy",
            {
                "name": policy,
                "type": "group",
                **common,
                "groups": [{"id": approver_id, "extendChildren": False}],
            },
        ),
        (
            "permission",
            {
                "name": f"{policy}:users",
                "type": "scope",
                **common,
                "resourceType": "Users",
                "resources": [],
                "scopes": USER_SCOPES,
                "policies": [policy],
            },
        ),
    ]
    if group_ids:
        entries.append(
            (
                "permission",
                {
                    "name": f"{policy}:groups",
                    "type": "scope",
                    **common,
                    "resourceType": "Groups",
                    "resources": sorted(group_ids),
                    "scopes": GROUP_SCOPES,
                    "policies": [policy],
                },
            )
        )
    return entries


def group_id(kc: Keycloak, path: str) -> str | None:
    """Return the id of the group at ``path``, or None when the realm lacks it.

    Args:
        kc: client.
        path: group path with one leading slash.
    """
    try:
        found, _ = kc.call(
            "GET", "group-by-path/" + urllib.parse.quote(path.strip("/"))
        )
    except KeycloakError as error:
        if str(error).endswith(NOT_FOUND):
            return None
        raise
    return found["id"]


def owned(kc: Keycloak, base: str, prefix: str) -> dict[str, dict]:
    """Return every policy and permission whose name carries ``prefix``, by name.

    Args:
        kc: client.
        base: path of the ``admin-permissions`` resource server.
        prefix: name prefix of every owned entry.
    """
    found: list[dict] = []
    while True:
        query = urllib.parse.urlencode({"first": len(found), "max": PAGE})
        page, _ = kc.call("GET", f"{base}/policy?{query}")
        found.extend(page)
        if len(page) < PAGE:
            break
    return {
        entry["name"]: entry
        for entry in found
        if entry["name"].startswith(f"{prefix}:")
    }


def write(
    kc: Keycloak,
    base: str,
    kind: str,
    body: dict,
    current: dict | None,
    ids: dict[str, str],
) -> str:
    """Create or update one entry and return its outcome.

    Args:
        kc: client.
        base: path of the ``admin-permissions`` resource server.
        kind: ``policy`` or ``permission``.
        body: the desired representation; the policy names in ``policies`` are
            sent as their ids.
        current: the entry as Keycloak lists it, or None when it is absent.
        ids: policy ids by name, extended by every policy written.
    """
    route = f"{base}/{ROUTES[kind]}"
    payload = {**body}
    if "policies" in payload:
        payload["policies"] = [ids[name] for name in payload["policies"]]
    payload["description"] = fingerprint(payload)
    if current is None:
        created, location = kc.call("POST", route, payload)
        ids[body["name"]] = (created or {}).get("id") or location
        if not ids[body["name"]]:
            raise KeycloakError(f"created {kind} {body['name']} carries no id")
        return "created"
    ids[body["name"]] = current["id"]
    if current.get("description") == payload["description"]:
        return "unchanged"
    kc.call("PUT", f"{route}/{current['id']}", {**payload, "id": current["id"]})
    return "updated"


def converge(kc: Keycloak, spec: dict) -> list[str]:
    """Return one ``<outcome> <kind> <name>`` line per owned entry and missing group.

    Args:
        kc: client.
        spec: the stdin object.
    """
    query = urllib.parse.urlencode(
        {"clientId": ADMIN_PERMISSIONS_CLIENT, "search": "false"}
    )
    clients, _ = kc.call("GET", f"clients?{query}")
    client = next(
        (c for c in clients if c["clientId"] == ADMIN_PERMISSIONS_CLIENT), None
    )
    if client is None:
        raise KeycloakError(
            f"the realm has no {ADMIN_PERMISSIONS_CLIENT} client, "
            "so adminPermissionsEnabled is off"
        )
    base = f"clients/{client['id']}/authz/resource-server"
    prefix = spec["prefix"]
    current = owned(kc, base, prefix)
    lines: list[str] = []
    ids: dict[str, str] = {}
    paths: dict[str, str | None] = {}

    def resolve(path: str) -> str | None:
        if path not in paths:
            paths[path] = group_id(kc, path)
            if paths[path] is None:
                lines.append(f"missing group {path}")
        return paths[path]

    wanted: set[str] = set()
    for entry in spec["approvers"]:
        approver_id = resolve(entry["approver"])
        if approver_id is None:
            continue
        group_ids = [gid for gid in map(resolve, entry["groups"]) if gid]
        for kind, body in desired(prefix, entry["approver"], approver_id, group_ids):
            wanted.add(body["name"])
            try:
                outcome = write(kc, base, kind, body, current.get(body["name"]), ids)
            except ERRORS as error:
                print(f"{kind} {body['name']}: {error}", file=sys.stderr)
                outcome = "failed"
            lines.append(f"{outcome} {kind} {body['name']}")
    stale = sorted(
        (entry for name, entry in current.items() if name not in wanted),
        key=lambda entry: (entry.get("type") == "group", entry["name"]),
    )
    for entry in stale:
        kind = "policy" if entry.get("type") == "group" else "permission"
        try:
            kc.call("DELETE", f"{base}/policy/{entry['id']}")
            outcome = "deleted"
        except ERRORS as error:
            print(f"{kind} {entry['name']}: {error}", file=sys.stderr)
            outcome = "failed"
        lines.append(f"{outcome} {kind} {entry['name']}")
    return lines


def main() -> int:
    env = os.environ
    try:
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        lines = converge(kc, json.load(sys.stdin))
    except ERRORS as error:
        print(f"listing-failed {error}")
        return 1
    for line in lines:
        print(line)
    outcomes = [line.split(" ", 1)[0] for line in lines]
    print("summary " + " ".join(f"{key}={outcomes.count(key)}" for key in OUTCOMES))
    return 1 if "failed" in outcomes else 0


if __name__ == "__main__":
    sys.exit(main())
