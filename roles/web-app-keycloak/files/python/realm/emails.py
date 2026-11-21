#!/usr/bin/env python3
"""Print the email address Keycloak holds for every user of a realm.

Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: realm holding the users.
    LDAP_COMPONENT_ID: user storage component synchronised in full before the read, empty for none.

Output: one JSON object mapping every username to its email address, users without one omitted.
Exit: 0 the object is complete, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

from keycloak_admin import Keycloak, KeycloakError, container_credentials

PAGE = 200


def emails(kc: Keycloak) -> dict[str, str]:
    """Return username to email of every user, read page by page.

    Args:
        kc: client.
    """
    found: dict[str, str] = {}
    first = 0
    while True:
        query = urllib.parse.urlencode(
            {"first": first, "max": PAGE, "briefRepresentation": "true"}
        )
        page, _ = kc.call("GET", f"users?{query}")
        for user in page:
            if user.get("email"):
                found[user["username"]] = user["email"]
        if len(page) < PAGE:
            return found
        first += PAGE


def main() -> int:
    env = os.environ
    try:
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        component = env["LDAP_COMPONENT_ID"]
        if component:
            kc.call(
                "POST",
                f"user-storage/{urllib.parse.quote(component, safe='')}/sync?action=triggerFullSync",
                timeout=600,
            )
        print(json.dumps(emails(kc), sort_keys=True))
    except (KeycloakError, OSError, KeyError, ValueError) as error:
        print(f"read-failed {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
