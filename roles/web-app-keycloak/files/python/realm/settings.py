#!/usr/bin/env python3
"""Converge Keycloak client scopes, clients and realm settings over the admin REST API.

Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: realm holding the client scopes and clients.

Stdin: JSON object with
    clientScopes: client scopes the realm gets when it has none of that name.
    clients: clients created when absent, updated when they drifted, their scope lists converged.
    realms: ``{"realm": <name>, "desired": <partial realm>}`` objects deep-merged into their realm.

Output: one ``<outcome> <kind> <name>`` line per object, then one ``summary`` line.
Exit: 0 every object converged, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from copy import deepcopy
from pathlib import Path

from keycloak_admin import Keycloak, KeycloakError, container_credentials

OUTCOMES = ("created", "updated", "unchanged", "failed")
SCOPE_LISTS = (
    ("defaultClientScopes", "default-client-scopes"),
    ("optionalClientScopes", "optional-client-scopes"),
)
CLIENT_KEYS = ("id", "clientId")
EMPTY = (None, "", [], {})
ERRORS = (KeycloakError, OSError, KeyError, TypeError, ValueError)


class RefusalError(Exception):
    pass


def deep_merge(base: dict, overlay: dict) -> dict:
    """Return ``base`` with ``overlay`` merged in: nested dicts merge, every other value is replaced.

    Args:
        base: the object as Keycloak holds it.
        overlay: the values to set.
    """
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def matches(desired: object, current: object) -> bool:
    """True when writing ``desired`` leaves ``current`` as Keycloak shows it.

    Args:
        desired: value to write. An empty value matches a key Keycloak omits.
        current: value Keycloak returned. Dict keys ``desired`` lacks are ignored, list order is not compared.
    """
    if isinstance(desired, dict):
        return isinstance(current, dict) and all(
            matches(value, current[key]) if key in current else value in EMPTY
            for key, value in desired.items()
        )
    if isinstance(desired, list):
        if not isinstance(current, list) or len(desired) != len(current):
            return False
        remaining = list(current)
        for item in desired:
            index = next(
                (i for i, have in enumerate(remaining) if matches(item, have)), -1
            )
            if index < 0:
                return False
            del remaining[index]
        return True
    return desired == current


def comparable(client: dict) -> dict:
    """Return the client fields a client PUT writes and Keycloak shows back.

    Args:
        client: client representation. Keycloak never shows the secret of a public or
            bearer-only client, and a client PUT ignores the scope lists.
    """
    hidden = {field for field, _ in SCOPE_LISTS}
    if client.get("publicClient") or client.get("bearerOnly"):
        hidden.add("secret")
    return {key: value for key, value in client.items() if key not in hidden}


def find_client(kc: Keycloak, client_id: str) -> dict | None:
    """Return the client whose clientId equals ``client_id``, or None.

    Args:
        kc: client.
        client_id: the clientId.
    """
    query = urllib.parse.urlencode({"clientId": client_id, "search": "false"})
    found, _ = kc.call("GET", f"clients?{query}")
    return next((c for c in found if c["clientId"] == client_id), None)


def create_scope(kc: Keycloak, scope: dict, catalog: dict[str, str]) -> str:
    """Return ``created`` or ``unchanged`` for a client scope; existing scopes stay as they are.

    Args:
        kc: client.
        scope: client scope representation.
        catalog: client scope ids by name, extended by the created scope.
    """
    if scope["name"] in catalog:
        return "unchanged"
    _, scope_id = kc.call("POST", "client-scopes", scope)
    if not scope_id:
        raise KeycloakError("created client scope carries no id")
    catalog[scope["name"]] = scope_id
    return "created"


def converge_scope_lists(
    kc: Keycloak, client_id: str, desired: dict, catalog: dict[str, str]
) -> bool:
    """Unassign and assign client scopes until the client's scope lists equal the desired ones.

    Args:
        kc: client.
        client_id: id of the client.
        desired: client representation naming the wanted scopes.
        catalog: client scope ids by name.

    Returns:
        True when a scope was unassigned or assigned.
    """
    plans = []
    for field, kind in SCOPE_LISTS:
        if field in desired:
            found, _ = kc.call("GET", f"clients/{client_id}/{kind}")
            current = {scope["name"]: scope["id"] for scope in found}
            plans.append((kind, set(desired[field]), current))
    unknown = sorted(
        name
        for _, wanted, current in plans
        for name in wanted - set(current)
        if name not in catalog
    )
    if unknown:
        raise RefusalError(f"client scopes missing in the realm: {', '.join(unknown)}")
    changed = False
    for kind, wanted, current in plans:
        for name in sorted(set(current) - wanted):
            kc.call("DELETE", f"clients/{client_id}/{kind}/{current[name]}")
            changed = True
    for kind, wanted, current in plans:
        for name in sorted(wanted - set(current)):
            kc.call("PUT", f"clients/{client_id}/{kind}/{catalog[name]}")
            changed = True
    return changed


def converge_client(
    kc: Keycloak, desired: dict, existing: dict | None, catalog: dict[str, str]
) -> str:
    """Return ``created``, ``updated`` or ``unchanged`` for a client.

    Args:
        kc: client.
        desired: client representation from the realm dictionary.
        existing: the client as Keycloak holds it, or None when it is absent.
        catalog: client scope ids by name.
    """
    if existing is None:
        try:
            kc.call("POST", "clients", desired)
        except KeycloakError:
            existing = find_client(kc, desired["clientId"])
            if existing is None:
                raise
        else:
            return "created"
    merged = {
        **deep_merge(existing, desired),
        **{key: existing[key] for key in CLIENT_KEYS},
    }
    written = not matches(comparable(merged), comparable(existing))
    if written:
        kc.call("PUT", f"clients/{existing['id']}", merged)
    scopes_changed = converge_scope_lists(kc, existing["id"], desired, catalog)
    return "updated" if written or scopes_changed else "unchanged"


def converge_realm(kc: Keycloak, realm: str, desired: dict) -> str:
    """Return ``updated`` or ``unchanged`` for a realm.

    Args:
        kc: client.
        realm: realm name.
        desired: realm fields deep-merged into the realm. Secrets Keycloak masks never
            match, so a desired secret is written on every run.
    """
    path = urllib.parse.quote(realm, safe="")
    current, _ = kc.admin("GET", path)
    merged = deep_merge(current, desired)
    if matches(merged, current):
        return "unchanged"
    kc.admin("PUT", path, merged)
    return "updated"


def main() -> int:
    env = os.environ
    try:
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        spec = json.load(sys.stdin)
        wanted_scopes, wanted_clients, wanted_realms = (
            spec["clientScopes"],
            spec["clients"],
            spec["realms"],
        )
        scopes, _ = kc.call("GET", "client-scopes")
        catalog = {scope["name"]: scope["id"] for scope in scopes}
        clients, _ = kc.call("GET", "clients")
        existing = {client["clientId"]: client for client in clients}
    except ERRORS as error:
        print(f"listing-failed {error}")
        return 1

    outcomes = []

    def record(kind: str, name: str, action, *args) -> None:
        try:
            outcome = action(*args)
        except (RefusalError, *ERRORS) as error:
            print(f"{kind} {name}: {error}", file=sys.stderr)
            outcome = "failed"
        print(f"{outcome} {kind} {name}")
        outcomes.append(outcome)

    for scope in wanted_scopes:
        record("client-scope", scope["name"], create_scope, kc, scope, catalog)
    for client in wanted_clients:
        name = client["clientId"]
        record("client", name, converge_client, kc, client, existing.get(name), catalog)
    for realm in wanted_realms:
        name = realm["realm"]
        record("realm", name, converge_realm, kc, name, realm["desired"])

    print("summary " + " ".join(f"{key}={outcomes.count(key)}" for key in OUTCOMES))
    return 1 if "failed" in outcomes else 0


if __name__ == "__main__":
    sys.exit(main())
