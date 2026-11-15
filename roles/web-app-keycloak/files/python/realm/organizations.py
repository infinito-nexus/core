"""
Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: the platform realm.
    KC_SERVICE_ACCOUNTS: JSON object of the clientIds whose service accounts converge,
        each to the JSON list of the roles it holds, exactly, of KC_ROLE_CLIENT.
    KC_ROLE_CLIENT: clientId of the client holding those roles.
    KC_ORGANIZATION_FLOW: alias of the flow holding the ``organization`` execution.
    KC_ORGANIZATION_REQUIREMENT: the requirement that execution holds.

Output: one ``granted role <name> to <client>``, ``revoked role <name> from <client>``
or ``updated execution organization <requirement>`` line per change, then
``summary changed=<n>``; ``failed <error>`` on a failure.
Exit: 0 converged, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

from keycloak_admin import Keycloak, KeycloakError, container_credentials

ERRORS = (KeycloakError, OSError, KeyError, TypeError, ValueError)
EXECUTION = "organization"


def client_uuid(kc: Keycloak, client_id: str) -> str:
    """
    Args:
        kc: client.
        client_id: a clientId.

    Returns:
        The client's internal id.
    """
    query = urllib.parse.urlencode({"clientId": client_id, "search": "false"})
    found, _ = kc.call("GET", f"clients?{query}")
    matching = [c["id"] for c in found if c["clientId"] == client_id]
    if len(matching) != 1:
        raise KeycloakError(f"the realm holds no single client {client_id}")
    return matching[0]


def converge_roles(
    kc: Keycloak, service_client: str, role_client: str, wanted: list[str]
) -> list[str]:
    """
    Args:
        kc: client.
        service_client: clientId of the client whose service account is converged.
        role_client: clientId of the client holding the roles.
        wanted: the roles the service account holds afterwards, and no other of role_client.

    Returns:
        One line per granted or revoked role.
    """
    account, _ = kc.call(
        "GET", f"clients/{client_uuid(kc, service_client)}/service-account-user"
    )
    roles_uuid = client_uuid(kc, role_client)
    path = f"users/{account['id']}/role-mappings/clients/{roles_uuid}"
    held, _ = kc.call("GET", path)
    names = {role["name"] for role in held}
    grant = [
        kc.call(
            "GET", f"clients/{roles_uuid}/roles/{urllib.parse.quote(name, safe='')}"
        )[0]
        for name in wanted
        if name not in names
    ]
    revoke = [role for role in held if role["name"] not in wanted]
    if grant:
        kc.call("POST", path, grant)
    if revoke:
        kc.call("DELETE", path, revoke)
    return [f"granted role {r['name']} to {service_client}" for r in grant] + [
        f"revoked role {r['name']} from {service_client}" for r in revoke
    ]


def converge_execution(kc: Keycloak, flow: str, requirement: str) -> list[str]:
    """
    Args:
        kc: client.
        flow: alias of the flow holding the ``organization`` execution.
        requirement: the requirement it holds afterwards.

    Returns:
        One line when the requirement changed, else none.
    """
    path = f"authentication/flows/{urllib.parse.quote(flow, safe='')}/executions"
    executions, _ = kc.call("GET", path)
    found = [e for e in executions if e.get("providerId") == EXECUTION]
    if len(found) != 1:
        raise KeycloakError(f"the flow {flow} holds no single {EXECUTION} execution")
    if found[0]["requirement"] == requirement:
        return []
    kc.call("PUT", path, {**found[0], "requirement": requirement})
    return [f"updated execution {EXECUTION} {requirement}"]


def main() -> int:
    env = os.environ
    try:
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        lines = [
            line
            for client, wanted in json.loads(env["KC_SERVICE_ACCOUNTS"]).items()
            for line in converge_roles(kc, client, env["KC_ROLE_CLIENT"], wanted)
        ] + converge_execution(
            kc, env["KC_ORGANIZATION_FLOW"], env["KC_ORGANIZATION_REQUIREMENT"]
        )
    except ERRORS as error:
        print(f"failed {error}")
        return 1
    for line in lines:
        print(line)
    print(f"summary changed={len(lines)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
