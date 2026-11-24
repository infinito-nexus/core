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
COMMON = {"logic": "POSITIVE", "decisionStrategy": "UNANIMOUS"}


def fingerprint(payload: dict) -> str:
    """Return the description that marks an entry as written from ``payload``.

    Args:
        payload: the representation Keycloak receives, without its description.
    """
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"Generated from meta/rbac.yml by web-app-keycloak; digest {digest[:16]}"


def group_policy(name: str, paths: list[str], approvers: dict[str, str]) -> dict:
    """Return a group policy that admits a member of any of ``paths``.

    Args:
        name: policy name.
        paths: approver group paths, sorted.
        approvers: Keycloak id of every approver group, by path.
    """
    return {
        "name": name,
        "type": "group",
        **COMMON,
        "groups": [{"id": approvers[path], "extendChildren": False} for path in paths],
    }


def scope_permission(
    name: str, resource_type: str, resources: list[str], scopes: list[str], policy: str
) -> dict:
    """Return a scope permission that names ``policy`` in ``policies`` by name.

    Args:
        name: permission name.
        resource_type: ``Users`` or ``Groups``.
        resources: resource ids; empty applies it to every resource of the type.
        scopes: granted scopes.
        policy: name of the policy deciding it.
    """
    return {
        "name": name,
        "type": "scope",
        **COMMON,
        "resourceType": resource_type,
        "resources": sorted(resources),
        "scopes": scopes,
        "policies": [policy],
    }


def desired(
    prefix: str, approvers: dict[str, str], grants: dict[str, set[str]]
) -> list[tuple[str, dict]]:
    """Return the ``(kind, representation)`` pairs the approver groups need.

    Args:
        prefix: name prefix of every owned entry.
        approvers: Keycloak id of every approver group, by path.
        grants: paths of the approver groups that may grant each group, by the
            group's Keycloak id.

    Returns:
        ``<prefix>:approvers`` with ``<prefix>:users`` for every user, then per
        distinct set of approvers a policy named by their joined paths with its
        ``:groups`` permission on the groups exactly that set may grant. Each
        policy precedes the permission that names it.
    """
    if not approvers:
        return []
    every = f"{prefix}:approvers"
    entries = [
        ("policy", group_policy(every, sorted(approvers), approvers)),
        (
            "permission",
            scope_permission(f"{prefix}:users", "Users", [], USER_SCOPES, every),
        ),
    ]
    by_set: dict[tuple[str, ...], list[str]] = {}
    for group, paths in grants.items():
        by_set.setdefault(tuple(sorted(paths)), []).append(group)
    for paths, groups in sorted(by_set.items()):
        policy = f"{prefix}:{','.join(paths)}"
        entries.append(("policy", group_policy(policy, list(paths), approvers)))
        entries.append(
            (
                "permission",
                scope_permission(
                    f"{policy}:groups", "Groups", groups, GROUP_SCOPES, policy
                ),
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

    approvers: dict[str, str] = {}
    grants: dict[str, set[str]] = {}
    for entry in spec["approvers"]:
        approver_id = resolve(entry["approver"])
        if approver_id is None:
            continue
        approvers[entry["approver"]] = approver_id
        for gid in filter(None, map(resolve, entry["groups"])):
            grants.setdefault(gid, set()).add(entry["approver"])
    wanted: set[str] = set()
    for kind, body in desired(prefix, approvers, grants):
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
