#!/usr/bin/env python3
"""Mark Keycloak email addresses verified over the admin REST API.

Two selections, one per run:

- inventory (``EMAILS``): the inventory address of every listed user;
- federation (``FEDERATION``): every address the realm's LDAP federation holds,
  the trust ``trustEmail`` gives a user Keycloak imports, extended to the users
  it imported before. Local users stay as they are.

Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: realm holding the users.
    EMAILS: JSON object mapping every username to the inventory address Keycloak's
        ``email`` field holds: the secondary address under the mailbox policy, the
        primary one under the external policy; empty for a user without one, such
        as a mailbox user without a secondary address.
    FEDERATION: name of the realm's LDAP user storage provider; when set, the
        federation selection runs and ``EMAILS`` is not read.

Output: one ``<outcome> <username>`` line per user, then one ``summary`` line.
Exit: 0 every selected user is verified, without an address, absent from the
realm or holds another address, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

from keycloak_admin import PAGE, Keycloak, KeycloakError, container_credentials

OUTCOMES = ("updated", "unchanged", "none", "missing", "foreign", "failed")
USER_STORAGE = "org.keycloak.storage.UserStorageProvider"
ERRORS = (KeycloakError, OSError, KeyError, ValueError)


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


def mark_verified(kc: Keycloak, user_id: str) -> None:
    """Write ``emailVerified: true`` onto the full representation of one user.

    Args:
        kc: client.
        user_id: the user's id.
    """
    current, _ = kc.call("GET", f"users/{user_id}")
    kc.call("PUT", f"users/{user_id}", {**current, "emailVerified": True})


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
    mark_verified(kc, user["id"])
    return "updated"


def federation_id(kc: Keycloak, name: str) -> str | None:
    """Return the id of the LDAP user storage provider named ``name``, or None.

    Args:
        kc: client.
        name: the provider's name.
    """
    query = urllib.parse.urlencode({"type": USER_STORAGE, "name": name})
    found, _ = kc.call("GET", f"components?{query}")
    return next(
        (
            component["id"]
            for component in found
            if component.get("providerId") == "ldap" and component.get("name") == name
        ),
        None,
    )


def federated_users(kc: Keycloak, provider_id: str) -> list[dict]:
    """Return every user of the realm linked to the provider, read page by page before any write.

    Args:
        kc: client.
        provider_id: the LDAP provider's id, as each user's ``federationLink`` names it.
    """
    found: list[dict] = []
    listed = 0
    while True:
        query = urllib.parse.urlencode(
            {"first": listed, "max": PAGE, "briefRepresentation": "true"}
        )
        page, _ = kc.call("GET", f"users?{query}")
        listed += len(page)
        found.extend(user for user in page if user.get("federationLink") == provider_id)
        if len(page) < PAGE:
            return found


def trust(kc: Keycloak, user: dict) -> str:
    """Return ``updated``, ``unchanged`` or ``none`` for one federated user.

    Args:
        kc: client.
        user: the user's brief representation.
    """
    if not str(user.get("email") or "").strip():
        return "none"
    if user.get("emailVerified") is True:
        return "unchanged"
    mark_verified(kc, user["id"])
    return "updated"


def load_addresses(raw: str) -> dict[str, str]:
    """Return the username to address map, refusing anything else.

    Args:
        raw: the JSON text of ``EMAILS``; an address may be empty.
    """
    addresses = json.loads(raw)
    if not isinstance(addresses, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in addresses.items()
    ):
        raise ValueError("EMAILS must map every username to an address string")
    return addresses


def run(selection: list[tuple[str, object]]) -> int:
    """Print one line per selected user and the summary, and return the exit code.

    Args:
        selection: ``(username, action)`` pairs; ``action`` returns the user's outcome.
    """
    outcomes = []
    for username, action in selection:
        try:
            outcome = action()
        except ERRORS as error:
            print(f"{username}: {error}", file=sys.stderr)
            outcome = "failed"
        print(f"{outcome} {username}")
        outcomes.append(outcome)

    print("summary " + " ".join(f"{key}={outcomes.count(key)}" for key in OUTCOMES))
    return 1 if "failed" in outcomes else 0


def inventory_selection(kc: Keycloak, addresses: dict[str, str]) -> list:
    """Return one ``(username, action)`` pair per inventory user.

    Args:
        kc: client.
        addresses: the username to inventory address map.
    """
    return [
        (username, lambda u=username, a=address: verify(kc, u, a))
        for username, address in addresses.items()
    ]


def federation_selection(kc: Keycloak, name: str) -> list:
    """Return one ``(username, action)`` pair per user of the LDAP provider.

    Args:
        kc: client.
        name: the LDAP provider's name; an absent provider yields one ``missing`` pair.
    """
    provider_id = federation_id(kc, name)
    if provider_id is None:
        return [(name, lambda: "missing")]
    return [
        (user["username"], lambda u=user: trust(kc, u))
        for user in federated_users(kc, provider_id)
    ]


def main() -> int:
    env = os.environ
    try:
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        selection = (
            federation_selection(kc, env["FEDERATION"])
            if "FEDERATION" in env
            else inventory_selection(kc, load_addresses(env["EMAILS"]))
        )
    except ERRORS as error:
        print(f"setup-failed {error}")
        return 1
    return run(selection)


if __name__ == "__main__":
    sys.exit(main())
