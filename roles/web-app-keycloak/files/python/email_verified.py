#!/usr/bin/env python3
"""Mark the email address of every listed Keycloak user verified over the admin REST API.

Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: realm holding the users.
    EMAILS_JSON: JSON object of username to the address the inventory declares for that user.

Output: one ``<outcome> <username>`` line per user, then one ``summary`` line.
Exit: 0 every user is verified, absent from the realm or holds another address, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

from keycloak_admin import Keycloak, KeycloakError, container_credentials

OUTCOMES = ("updated", "unchanged", "mismatch", "missing", "failed")


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


def verify(kc: Keycloak, username: str, email: str) -> str:
    """Return ``updated``, ``unchanged``, ``mismatch`` or ``missing`` for a user.

    Args:
        kc: client.
        username: the user whose email address gets marked verified.
        email: the address the inventory declares; a user holding any other address stays as it is.
    """
    user = find_user(kc, username)
    if user is None:
        return "missing"
    held = user.get("email")
    if not isinstance(held, str) or held.lower() != email.lower():
        return "mismatch"
    if user.get("emailVerified") is True:
        return "unchanged"
    current, _ = kc.call("GET", f"users/{user['id']}")
    kc.call("PUT", f"users/{user['id']}", {**current, "emailVerified": True})
    return "updated"


def load_emails(raw: str) -> dict[str, str]:
    """Return the username to address map, refusing anything else.

    Args:
        raw: the JSON text of ``EMAILS_JSON``.
    """
    emails = json.loads(raw)
    if not isinstance(emails, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and value
        for key, value in emails.items()
    ):
        raise ValueError("EMAILS_JSON must map every username to a non-empty address")
    return emails


def main() -> int:
    env = os.environ
    try:
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        emails = load_emails(env["EMAILS_JSON"])
    except (OSError, KeyError, ValueError) as error:
        print(f"setup-failed {error}")
        return 1

    outcomes = []
    for username, email in emails.items():
        try:
            outcome = verify(kc, username, email)
        except (KeycloakError, OSError, KeyError, ValueError) as error:
            print(f"{username}: {error}", file=sys.stderr)
            outcome = "failed"
        print(f"{outcome} {username}")
        outcomes.append(outcome)

    print("summary " + " ".join(f"{key}={outcomes.count(key)}" for key in OUTCOMES))
    return 1 if "failed" in outcomes else 0


if __name__ == "__main__":
    sys.exit(main())
