#!/usr/bin/env python3
"""Mark the email address of every listed Keycloak user verified over the admin REST API.

Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: realm holding the users.
    USERNAMES: space-separated usernames to mark verified.

Output: one ``<outcome> <username>`` line per user, then one ``summary`` line.
Exit: 0 every user is verified or absent from the realm, 1 otherwise.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
from pathlib import Path

from keycloak_admin import Keycloak, KeycloakError, container_credentials

OUTCOMES = ("updated", "unchanged", "missing", "failed")


def find_user(kc: Keycloak, username: str) -> dict | None:
    """Return the user whose username equals ``username``, or None.

    Args:
        kc: client.
        username: the username, compared case-insensitively as Keycloak stores it lowercased.
    """
    query = urllib.parse.urlencode({"username": username, "exact": "true"})
    found, _ = kc.call("GET", f"users?{query}")
    wanted = username.lower()
    return next((user for user in found if user["username"].lower() == wanted), None)


def verify(kc: Keycloak, username: str) -> str:
    """Return ``updated``, ``unchanged`` or ``missing`` for a user.

    Args:
        kc: client.
        username: the user whose email address gets marked verified.
    """
    user = find_user(kc, username)
    if user is None:
        return "missing"
    if user.get("emailVerified") is True:
        return "unchanged"
    current, _ = kc.call("GET", f"users/{user['id']}")
    kc.call("PUT", f"users/{user['id']}", {**current, "emailVerified": True})
    return "updated"


def main() -> int:
    env = os.environ
    try:
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        usernames = env["USERNAMES"].split()
    except (OSError, KeyError, ValueError) as error:
        print(f"setup-failed {error}")
        return 1

    outcomes = []
    for username in usernames:
        try:
            outcome = verify(kc, username)
        except (KeycloakError, OSError, KeyError, ValueError) as error:
            print(f"{username}: {error}", file=sys.stderr)
            outcome = "failed"
        print(f"{outcome} {username}")
        outcomes.append(outcome)

    print("summary " + " ".join(f"{key}={outcomes.count(key)}" for key in OUTCOMES))
    return 1 if "failed" in outcomes else 0


if __name__ == "__main__":
    sys.exit(main())
