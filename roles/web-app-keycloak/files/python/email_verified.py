#!/usr/bin/env python3
"""Mark the inventory email address of every listed Keycloak user verified over the admin REST API.

Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: realm holding the users.
    EMAILS: JSON object mapping every username to the inventory address Keycloak's
        ``email`` field holds: the secondary address under the mailbox policy, the
        primary one under the external policy; empty for a user without one, such
        as a mailbox user without a secondary address.

Output: one ``<outcome> <username>`` line per user, then one ``summary`` line.
Exit: 0 every user is verified, without an inventory address, absent from the
realm or holds another address, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

from keycloak_admin import Keycloak, KeycloakError, container_credentials

OUTCOMES = ("updated", "unchanged", "none", "missing", "foreign", "failed")


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


def verify(kc: Keycloak, username: str, address: str) -> str:
    """Return ``updated``, ``unchanged``, ``none``, ``missing`` or ``foreign`` for a user.

    Args:
        kc: client.
        username: the user whose email address gets marked verified.
        address: the inventory address; only an equal Keycloak address is
            marked verified, so an address the user set and never confirmed stays
            unverified. Empty skips the user without a lookup.
    """
    if not address:
        return "none"
    user = find_user(kc, username)
    if user is None:
        return "missing"
    if str(user.get("email") or "").lower() != address.lower():
        return "foreign"
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
        addresses = json.loads(env["EMAILS"])
    except (OSError, KeyError, ValueError) as error:
        print(f"setup-failed {error}")
        return 1

    outcomes = []
    for username, address in addresses.items():
        try:
            outcome = verify(kc, username, address)
        except (KeycloakError, OSError, KeyError, ValueError) as error:
            print(f"{username}: {error}", file=sys.stderr)
            outcome = "failed"
        print(f"{outcome} {username}")
        outcomes.append(outcome)

    print("summary " + " ".join(f"{key}={outcomes.count(key)}" for key in OUTCOMES))
    return 1 if "failed" in outcomes else 0


if __name__ == "__main__":
    sys.exit(main())
