"""Converge the Synapse admin flag on the administrator role group.

Environment:
    MATRIX_SYNAPSE_URL: Synapse's loopback URL on the node.
    MATRIX_SERVER_NAME: the homeserver name of the user ids.
    MATRIX_ADMIN_USERNAME, MATRIX_ADMIN_PASSWORD: the platform administrator.
    MATRIX_RBAC_PROTECTED_MXIDS: JSON list of user ids that keep the flag.
    MATRIX_RBAC_PAGE_SIZE: how many accounts one listing returns.
    RBAC_ADMINISTRATORS: JSON list of the administrator role's usernames.

Output:
    One ``CHANGED <user id> admin=<flag>`` line per changed account, else ``UNCHANGED``.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

LOGIN_ATTEMPTS = 10
LOGIN_DELAY_SECONDS = 6


def mxid(username, server_name):
    """Return the lowercased Matrix user id of ``username``.

    Args:
        username: the localpart, with or without a leading ``@``.
        server_name: the homeserver name.
    """
    return f"@{username.lstrip('@')}:{server_name}".lower()


def call(environ, opener, path, method, body, token):
    """Return the decoded JSON answer of one Synapse request.

    Args:
        environ: the process environment.
        opener: ``urllib.request.urlopen`` or a stand-in.
        path: path below the Synapse URL.
        method: the HTTP method.
        body: the JSON body, or None.
        token: an access token, or an empty string.
    """
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(  # noqa: S310 - MATRIX_SYNAPSE_URL is the node-local Synapse port
        environ["MATRIX_SYNAPSE_URL"] + path,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers,
        method=method,
    )
    with opener(request, timeout=30) as response:
        return json.loads(response.read().decode() or "{}")


def login(environ, opener, sleep):
    """Return an access token of the platform administrator, retrying while Synapse starts.

    Args:
        environ: the process environment.
        opener: ``urllib.request.urlopen`` or a stand-in.
        sleep: ``time.sleep`` or a stand-in.
    """
    body = {
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": environ["MATRIX_ADMIN_USERNAME"]},
        "password": environ["MATRIX_ADMIN_PASSWORD"],
        "initial_device_display_name": "infinito-rbac-reconcile",
    }
    for attempt in range(LOGIN_ATTEMPTS):
        try:
            return call(environ, opener, "/_matrix/client/v3/login", "POST", body, "")[
                "access_token"
            ]
        except urllib.error.URLError:
            if attempt == LOGIN_ATTEMPTS - 1:
                raise
            sleep(LOGIN_DELAY_SECONDS)
    raise RuntimeError("unreachable")


def plan(users, members, protected):
    """Return ``(user id, admin flag)`` pairs that bring Synapse in line with the group.

    Args:
        users: the Synapse admin API's user listing.
        members: user ids of the administrator role's members.
        protected: user ids that keep the admin flag.
    """
    changes = []
    for user in users:
        name = user["name"]
        if name in members and not user["admin"]:
            changes.append((name, True))
        elif user["admin"] and name not in members and name not in protected:
            changes.append((name, False))
    return changes


def main(environ, opener=urllib.request.urlopen, sleep=time.sleep):
    """Apply the plan with an admin session that is always logged out.

    Args:
        environ: the process environment.
        opener: ``urllib.request.urlopen`` or a stand-in.
        sleep: ``time.sleep`` or a stand-in.
    """
    server = environ["MATRIX_SERVER_NAME"]
    members = {
        mxid(name, server) for name in json.loads(environ["RBAC_ADMINISTRATORS"])
    }
    protected = {
        name.lower() for name in json.loads(environ["MATRIX_RBAC_PROTECTED_MXIDS"])
    }
    token = login(environ, opener, sleep)
    try:
        listing = call(
            environ,
            opener,
            f"/_synapse/admin/v2/users?guests=false&deactivated=false&limit={environ['MATRIX_RBAC_PAGE_SIZE']}",
            "GET",
            None,
            token,
        )
        if "next_token" in listing:
            raise SystemExit(
                f"Synapse holds more than {environ['MATRIX_RBAC_PAGE_SIZE']} accounts; raise MATRIX_RBAC_USER_PAGE_SIZE"
            )
        changes = plan(listing["users"], members, protected)
        for name, admin in changes:
            call(
                environ,
                opener,
                f"/_synapse/admin/v2/users/{urllib.parse.quote(name)}",
                "PUT",
                {"admin": admin},
                token,
            )
    finally:
        call(environ, opener, "/_matrix/client/v3/logout", "POST", {}, token)
    print(
        "\n".join(
            f"CHANGED {name} admin={str(admin).lower()}" for name, admin in changes
        )
        or "UNCHANGED"
    )


if __name__ == "__main__":
    main(os.environ)
