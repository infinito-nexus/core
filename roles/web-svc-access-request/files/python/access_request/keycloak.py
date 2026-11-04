"""Group grants against the Keycloak admin REST API with the approver's own token.

The service holds no Keycloak credential. Keycloak authenticates the bearer
token of the approving administrator, takes the realm from its issuer and lets
its fine-grained admin permissions decide each membership, so a grant the
approver may not make fails here with 403.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class GrantError(Exception):
    """Keycloak refused or failed a call."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status} {message}")
        self.status = status


@dataclass(frozen=True)
class Realm:
    """Where the admin REST API of the realm answers.

    Args:
        base_url: Keycloak base URL, the issuer host of the realm's tokens.
        realm: realm name.
        console_url: base URL of the realm's admin console.
        ca_file: CA bundle to trust, empty for the system store.
    """

    base_url: str
    realm: str
    console_url: str
    ca_file: str

    def admin(self, path: str) -> str:
        return (
            f"{self.base_url.rstrip('/')}/admin/realms/"
            f"{urllib.parse.quote(self.realm, safe='')}/{path}"
        )

    def user_groups_console(self, user_id: str) -> str:
        """Return the admin console page listing a user's groups.

        Args:
            user_id: Keycloak user id.
        """
        return (
            f"{self.console_url.rstrip('/')}/#/{urllib.parse.quote(self.realm, safe='')}"
            f"/users/{urllib.parse.quote(user_id, safe='')}/groups"
        )


def _call(realm: Realm, token: str, method: str, path: str):
    request = urllib.request.Request(  # noqa: S310 - realm.base_url is the deploy-time Keycloak URL
        realm.admin(path),
        method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    context = ssl.create_default_context(cafile=realm.ca_file or None)
    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as response:  # noqa: S310 - see above
            body = response.read()
    except urllib.error.HTTPError as error:
        raise GrantError(error.code, error.reason) from error
    except urllib.error.URLError as error:
        raise GrantError(0, str(error.reason)) from error
    return json.loads(body) if body else None


def user_groups(realm: Realm, token: str, user_id: str) -> list[str]:
    """Return the group paths a user holds now.

    Args:
        realm: the realm.
        token: the approver's access token; needs ``view`` on the user.
        user_id: Keycloak user id.
    """
    found = _call(
        realm,
        token,
        "GET",
        f"users/{urllib.parse.quote(user_id, safe='')}/groups?briefRepresentation=true",
    )
    return sorted(group["path"] for group in found or [])


def group_id(realm: Realm, token: str, path: str) -> str:
    """Return the id of the group at ``path``.

    Args:
        realm: the realm.
        token: the approver's access token; needs ``view`` on the group.
        path: group path with one leading slash.
    """
    found = _call(
        realm, token, "GET", "group-by-path/" + urllib.parse.quote(path.lstrip("/"))
    )
    return found["id"]


def grant(realm: Realm, token: str, user_id: str, paths: list[str]) -> list[str]:
    """Add a user to groups and return the paths Keycloak accepted.

    Args:
        realm: the realm.
        token: the approver's access token; needs ``manage-group-membership``
            on the user and ``view`` plus ``manage-membership`` on each group.
        user_id: Keycloak user id of the requester.
        paths: group paths to join.

    Raises:
        GrantError: Keycloak failed with anything but a refusal, which skips
            the group instead.
    """
    accepted = []
    for path in paths:
        try:
            gid = group_id(realm, token, path)
            _call(
                realm,
                token,
                "PUT",
                f"users/{urllib.parse.quote(user_id, safe='')}/groups/{gid}",
            )
        except GrantError as error:
            if error.status in (403, 404):
                continue
            raise
        accepted.append(path)
    return accepted
