#!/usr/bin/env python3
"""Ensure the realm RBAC group paths and their memberships over the admin REST API.

Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: realm holding the groups and users.

Stdin: JSON list of ``{"path": "<root>/<app>/<role>", "members": [username, ...]}``.

Output: one ``<outcome> group /<path>`` line per group and one
``<outcome> member /<path> <username>`` line per membership, then one ``summary`` line.
Exit: 0 every group exists and holds every listed member, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

from keycloak_admin import PAGE, Keycloak, KeycloakError, container_credentials

OUTCOMES = ("created", "joined", "unchanged", "missing", "failed")
ERRORS = (KeycloakError, OSError, KeyError, TypeError, ValueError)


def paged(kc: Keycloak, route: str) -> list[dict]:
    """Return every entry of a paged listing.

    Args:
        kc: client.
        route: path below ``/admin/realms/<realm>/`` without a query.
    """
    found: list[dict] = []
    while True:
        query = urllib.parse.urlencode(
            {"first": len(found), "max": PAGE, "briefRepresentation": "true"}
        )
        page, _ = kc.call("GET", f"{route}?{query}")
        found.extend(page)
        if len(page) < PAGE:
            return found


class Tree:
    """Group ids by name per parent, each parent listed at most once.

    Args:
        kc: client.
    """

    def __init__(self, kc: Keycloak) -> None:
        self.kc = kc
        self._children: dict[str, dict[str, str]] = {}

    def _listing(self, parent_id: str) -> dict[str, str]:
        if parent_id not in self._children:
            groups = (
                self.kc.children(parent_id) if parent_id else paged(self.kc, "groups")
            )
            self._children[parent_id] = {group["name"]: group["id"] for group in groups}
        return self._children[parent_id]

    def ensure(self, path: str) -> tuple[str, bool]:
        """Return the leaf group id of a path and whether the leaf was created.

        Args:
            path: slash-separated group path, e.g. ``/roles/web-app-matomo/administrator``.
        """
        parent_id, created = "", False
        for name in filter(None, path.split("/")):
            listing = self._listing(parent_id)
            group_id = listing.get(name)
            created = not group_id
            if created:
                target = f"groups/{parent_id}/children" if parent_id else "groups"
                _, group_id = self.kc.call("POST", target, {"name": name})
                if not group_id:
                    raise KeycloakError(f"created group {name} carries no id")
                listing[name] = group_id
                self._children[group_id] = {}
            parent_id = group_id
        if not parent_id:
            raise ValueError("empty group path")
        return parent_id, created


class Members:
    """User ids and memberships, each user looked up and listed at most once.

    Args:
        kc: client.
    """

    def __init__(self, kc: Keycloak) -> None:
        self.kc = kc
        self._ids: dict[str, str | None] = {}
        self._groups: dict[str, set[str]] = {}

    def _user_id(self, username: str) -> str | None:
        wanted = username.lower()
        if wanted not in self._ids:
            query = urllib.parse.urlencode({"username": username, "exact": "true"})
            found, _ = self.kc.call("GET", f"users?{query}")
            self._ids[wanted] = next(
                (user["id"] for user in found if user["username"].lower() == wanted),
                None,
            )
        return self._ids[wanted]

    def _read(self, user_id: str) -> set[str]:
        self._groups[user_id] = {
            group["id"] for group in paged(self.kc, f"users/{user_id}/groups")
        }
        return self._groups[user_id]

    def join(self, username: str, group_id: str) -> str:
        """Return ``joined``, ``unchanged`` or ``missing`` for one membership.

        Args:
            username: the user, compared case-insensitively as Keycloak stores it lowercased.
            group_id: the group the user must be a direct member of.
        """
        user_id = self._user_id(username)
        if user_id is None:
            return "missing"
        have = self._groups.get(user_id)
        if have is None:
            have = self._read(user_id)
        if group_id in have:
            return "unchanged"
        self.kc.call("PUT", f"users/{user_id}/groups/{group_id}")
        if group_id not in self._read(user_id):
            raise KeycloakError(f"membership of {username} not visible after the join")
        return "joined"


def converge(kc: Keycloak, groups: list[dict]) -> list[str]:
    """Return one ``<outcome> <kind> <name>`` line per group and membership.

    Args:
        kc: client.
        groups: ``{"path": ..., "members": [...]}`` objects.
    """
    tree, members, lines = Tree(kc), Members(kc), []
    for group in groups:
        path = "/" + group["path"].strip("/")
        try:
            leaf, created = tree.ensure(path)
        except ERRORS as error:
            print(f"group {path}: {error}", file=sys.stderr)
            lines.append(f"failed group {path}")
            continue
        lines.append(f"{'created' if created else 'unchanged'} group {path}")
        for username in group["members"]:
            try:
                outcome = members.join(username, leaf)
            except ERRORS as error:
                print(f"member {path} {username}: {error}", file=sys.stderr)
                outcome = "failed"
            lines.append(f"{outcome} member {path} {username}")
    return lines


def main() -> int:
    env = os.environ
    try:
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        groups = json.load(sys.stdin)
        lines = converge(kc, groups)
    except ERRORS as error:
        print(f"listing-failed {error}")
        return 1
    for line in lines:
        print(line)
    outcomes = [line.split(" ", 1)[0] for line in lines]
    print("summary " + " ".join(f"{key}={outcomes.count(key)}" for key in OUTCOMES))
    return 1 if {"missing", "failed"} & set(outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
