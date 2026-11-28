"""
Env:
    KC_URL: Keycloak base URL.
    KC_REALM: the platform realm.
    KC_CLIENT_ID: the client ``workspace-members``.
    KC_CLIENT_SECRET_FILE: file holding that client's secret.
    KC_RBAC_GROUP_ROOT: path of the RBAC group root.
    USER_ACTION: ``erase`` deletes the platform account of USER_ID in Keycloak and,
        through the writable LDAP federation, in the directory.
    USER_ID: the Keycloak user id.

Output: ``erased user <id>`` for the deletion; the last line is
``{"user":"<id>","erased":true}`` or ``{"user":"<id>","refused":"<reason>"}``,
reason ``member`` or ``platform_role``. No address is printed.
Exit: 0 erased, 3 refused, 1 failed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse

from keycloak_admin import KeycloakError, KeycloakHTTPError, ServiceAccount
from workspaces import (
    RefusalError,
    keycloak_id,
    marked_workspaces,
    rbac_member,
    refusal_line,
    service_account,
)

ACTIONS = ("erase",)
REFUSED = 3
FAILED = 1
NOT_FOUND = 404
ERRORS = (KeycloakError, OSError, KeyError, TypeError, ValueError)


def account(kc: ServiceAccount, user_id: str) -> dict | None:
    """
    Args:
        kc: client.
        user_id: the user.

    Returns:
        The user, or None when Keycloak holds no user of that id.
    """
    try:
        found, _ = kc.call("GET", f"users/{user_id}")
    except KeycloakHTTPError as error:
        if error.status == NOT_FOUND:
            return None
        raise
    return found


def workspace_member(kc: ServiceAccount, user_id: str) -> bool:
    """
    Args:
        kc: client.
        user_id: the user.

    Returns:
        True when the user is a member of an organization carrying a workspace marker.
    """
    return bool(marked_workspaces(kc, user_id))


def directory_holds(kc: ServiceAccount, username: str) -> bool:
    """
    Args:
        kc: client.
        username: the erased user's username.

    Returns:
        True when a lookup, which also searches the LDAP federation, still finds it.
    """
    query = urllib.parse.urlencode({"username": username, "exact": "true"})
    found, _ = kc.call("GET", f"users?{query}")
    return bool(found)


def erase(kc: ServiceAccount, user_id: str, root: str, log) -> None:
    """
    Args:
        kc: client.
        user_id: the user.
        root: path of the RBAC group root.
        log: sink of the change line.
    """
    user = account(kc, user_id)
    if user is None:
        return
    if workspace_member(kc, user_id):
        raise RefusalError("member")
    if rbac_member(kc, user_id, root):
        raise RefusalError("platform_role")
    try:
        kc.call("DELETE", f"users/{user_id}")
    except KeycloakHTTPError as error:
        if error.status != NOT_FOUND:
            raise
    if directory_holds(kc, user["username"]):
        raise KeycloakError(f"the directory still holds the account of {user_id}")
    log(f"erased user {user_id}")


def main() -> int:
    env = dict(os.environ)
    user_id = env.get("USER_ID", "")
    try:
        keycloak_id(user_id, "USER_ID")
        if env["USER_ACTION"] not in ACTIONS:
            raise ValueError("USER_ACTION is not erase")
        erase(service_account(env), user_id, env["KC_RBAC_GROUP_ROOT"], print)
    except RefusalError as refusal:
        print(refusal_line("user", user_id, refusal.reason))
        return REFUSED
    except ERRORS as error:
        print(f"failed {error}", file=sys.stderr)
        return FAILED
    print(json.dumps({"user": user_id, "erased": True}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
