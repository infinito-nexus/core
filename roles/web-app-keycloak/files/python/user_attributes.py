#!/usr/bin/env python3
"""
Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: realm holding the users.
    ATTRIBUTE: the user attribute to write.
    USERS: JSON list of ``{"id": <user id>, "value": <wanted value>}``.

Output: one ``<outcome> <user id>`` line per entry, one ``USER_ATTRIBUTES`` JSON
line listing every entry with its ``outcome`` and the values the user ``held``
before, then one ``summary`` line. ``updated`` and ``unchanged`` leave the user
holding the value; ``conflict`` (another value held, left as it is),
``taken`` (the username of a user no entry hands the value, left unwritten), ``missing``,
``dropped`` (Keycloak kept no value) and ``failed`` do not.
Exit: 0 when no entry failed, 1 when one did, 2 when the run could not start.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

from keycloak_admin import Keycloak, KeycloakError, container_credentials

OUTCOMES = (
    "updated",
    "unchanged",
    "conflict",
    "taken",
    "missing",
    "dropped",
    "failed",
)
ERRORS = (KeycloakError, OSError, KeyError, ValueError)


def held_values(kc: Keycloak, user_id: str, attribute: str) -> tuple[dict, list] | None:
    """
    Args:
        kc: client.
        user_id: the user's id.
        attribute: the user attribute to read.

    Returns:
        The user's full representation and the values it holds for ``attribute``,
        or None when the realm has no such user or the id is empty or dots only.
    """
    if not user_id.strip("."):
        return None
    try:
        user, _ = kc.call("GET", f"users/{urllib.parse.quote(user_id, safe='')}")
    except KeycloakError as error:
        if str(error).endswith("HTTP 404"):
            return None
        raise
    return user, list((user.get("attributes") or {}).get(attribute) or [])


def taken(kc: Keycloak, value: str, owners: set[str]) -> bool:
    """
    Args:
        kc: client.
        value: the value to write.
        owners: the ids of every user the entries hand this value.

    Returns:
        Whether a user outside ``owners`` has the value as username.
    """
    query = urllib.parse.urlencode(
        {"username": value.lower(), "exact": "true", "briefRepresentation": "true"}
    )
    users, _ = kc.call("GET", f"users?{query}")
    return any(user.get("id") not in owners for user in users or [])


def write(
    kc: Keycloak, attribute: str, user_id: str, value: str, owners: set[str]
) -> tuple[str, list]:
    """
    Args:
        kc: client.
        attribute: the user attribute to write.
        user_id: the user's id.
        value: the value the user should hold.
        owners: the ids of every user the entries hand this value.

    Returns:
        The outcome and the values the user held before.
    """
    found = held_values(kc, user_id, attribute)
    if found is None:
        return "missing", []
    user, held = found
    if any(held) and held != [value]:
        return "conflict", held
    if taken(kc, value, owners):
        return "taken", held
    if held == [value]:
        return "unchanged", held
    attributes = {**(user.get("attributes") or {}), attribute: [value]}
    kc.call(
        "PUT",
        f"users/{urllib.parse.quote(user_id, safe='')}",
        {**user, "attributes": attributes},
    )
    after = held_values(kc, user_id, attribute)
    return ("updated" if after is not None and after[1] == [value] else "dropped"), held


def run(kc: Keycloak, attribute: str, users: list[dict]) -> int:
    """
    Args:
        kc: client.
        attribute: the user attribute to write.
        users: the ``{"id", "value"}`` entries, handled in order.

    Returns:
        The exit code: 1 when an entry failed, 0 otherwise.
    """
    owners: dict[str, set[str]] = {}
    for entry in users:
        owners.setdefault(entry["value"].lower(), set()).add(entry["id"])
    results = []
    for entry in users:
        try:
            outcome, held = write(
                kc,
                attribute,
                entry["id"],
                entry["value"],
                owners[entry["value"].lower()],
            )
        except ERRORS:
            outcome, held = "failed", []
        print(f"{outcome} {entry['id']}")
        results.append({**entry, "outcome": outcome, "held": held})
    print("USER_ATTRIBUTES " + json.dumps(results))
    outcomes = [result["outcome"] for result in results]
    print("summary " + " ".join(f"{key}={outcomes.count(key)}" for key in OUTCOMES))
    return 1 if "failed" in outcomes else 0


def main() -> int:
    env = os.environ
    try:
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        users = [
            {"id": str(entry["id"]), "value": str(entry["value"])}
            for entry in json.loads(env["USERS"])
        ]
        attribute = env["ATTRIBUTE"]
    except (*ERRORS, TypeError) as error:
        print(f"setup-failed {error}")
        return 2
    return run(kc, attribute, users)


if __name__ == "__main__":
    sys.exit(main())
