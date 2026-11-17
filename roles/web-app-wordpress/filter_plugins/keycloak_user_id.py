from __future__ import annotations

import json

from ansible.errors import AnsibleFilterError


def keycloak_user_id(users_json, username):
    """Return the id of the one Keycloak user named ``username``.

    Args:
        users_json: stdout of ``kcadm.sh get users --fields id,username``, a JSON list.
        username: the username to match, compared case-insensitively as Keycloak stores it lowercased.

    Returns:
        The user's id, which Keycloak sends as the ``sub`` claim.

    Raises:
        AnsibleFilterError: when the output is no JSON list or not exactly one user with an id matches.
    """
    try:
        users = json.loads(users_json)
    except (TypeError, ValueError) as exc:
        raise AnsibleFilterError(f"kcadm printed no JSON user list ({exc})") from exc
    if not isinstance(users, list):
        raise AnsibleFilterError("kcadm printed no JSON user list")
    wanted = str(username).lower()
    ids = [
        user.get("id")
        for user in users
        if isinstance(user, dict) and str(user.get("username", "")).lower() == wanted
    ]
    if len(ids) != 1 or not isinstance(ids[0], str) or not ids[0]:
        raise AnsibleFilterError(
            f"expected exactly one Keycloak user named '{username}' with an id, found {len(ids)} matches"
        )
    return ids[0]


class FilterModule:
    """Pick the Keycloak user a WordPress account is bound to."""

    def filters(self):
        return {"keycloak_user_id": keycloak_user_id}
