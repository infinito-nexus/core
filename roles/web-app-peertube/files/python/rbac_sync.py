"""Create the missing OIDC accounts of the role group members, then converge every account's role.

Files:
    select-members-without-account.sql, link-preprovisioned-accounts.sql, reconcile-roles.sql:
        beside this script, run through psql in the database container.

Environment:
    RBAC_SYNC_CONTAINER_BIN, RBAC_SYNC_CID: how to reach the database container.
    PGPASSWORD: password of the PeerTube database user.
    PEERTUBE_DB_USER, PEERTUBE_DB_NAME: the PeerTube database user and database.
    PEERTUBE_URL: PeerTube's local URL on the node.
    PEERTUBE_HOSTNAME: Host header PeerTube answers to.
    PEERTUBE_ROOT_USERNAME, PEERTUBE_ROOT_PASSWORD: the local root account.
    PEERTUBE_RBAC_ROLE_IDS: JSON ``{role: PeerTube role id}`` of administrator and moderator.
    PEERTUBE_OIDC_PLUGIN: name of the OIDC plugin the accounts belong to.
    RBAC_MEMBERS: JSON ``{role: [{username, email, name}]}`` of administrator and moderator.

Output:
    One ``CHANGED <username> created`` line per created account, then the lines of
    reconcile-roles.sql.
"""

import json
import os
import secrets
import string
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PASSWORD_ALPHABET = string.ascii_letters + string.digits


def psql(environ, run, script, names, extra):
    """Return the output of one SQL file run through psql in the database container.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        script: name of the SQL file beside this script.
        names: variables the SQL reads, forwarded into the container by name.
        extra: variables added to the environment for this run.
    """
    argv = [environ["RBAC_SYNC_CONTAINER_BIN"], "exec", "-i", "-e", "PGPASSWORD"]
    for name in names:
        argv += ["-e", name]
    argv += [
        environ["RBAC_SYNC_CID"],
        "psql",
        "-U",
        environ["PEERTUBE_DB_USER"],
        "-d",
        environ["PEERTUBE_DB_NAME"],
        "-v",
        "ON_ERROR_STOP=1",
        "-qtA",
    ]
    result = run(
        argv,
        input=Path(script).read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=True,
        env={**environ, **extra},
    )
    return result.stdout


def ranked_members(members, role_ids):
    """Return every member with an e-mail and the highest PeerTube role it holds.

    Args:
        members: ``{role: [{username, email, name}]}``.
        role_ids: ``{role: PeerTube role id}``.
    """
    administrators = [m for m in members["administrator"] if m["email"]]
    taken = {m["username"] for m in administrators}
    moderators = [
        m for m in members["moderator"] if m["email"] and m["username"] not in taken
    ]
    return [
        {
            "username": m["username"],
            "email": m["email"],
            "role": role_ids["administrator"],
        }
        for m in administrators
    ] + [
        {"username": m["username"], "email": m["email"], "role": role_ids["moderator"]}
        for m in moderators
    ]


def api(environ, opener, path, data=None, form=False, token=""):
    """Return the decoded JSON answer of one PeerTube API request, or None for a 409.

    Args:
        environ: the process environment.
        opener: ``urllib.request.urlopen`` or a stand-in.
        path: path below the PeerTube URL.
        data: request body, or None for a GET.
        form: whether the body is form-encoded instead of JSON.
        token: bearer token, or an empty string.
    """
    headers = {"Host": environ["PEERTUBE_HOSTNAME"]}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(  # noqa: S310 - PEERTUBE_URL is the node-local PeerTube port
        environ["PEERTUBE_URL"] + path, data=body, headers=headers
    )
    try:
        with opener(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        if error.code == 409:
            return None
        raise
    return json.loads(raw) if raw else {}


def create_accounts(environ, opener, missing):
    """Create the missing accounts as root and return their e-mails.

    Args:
        environ: the process environment.
        opener: ``urllib.request.urlopen`` or a stand-in.
        missing: ``[{username, email, role}]`` without a PeerTube account.
    """
    client = api(environ, opener, "/api/v1/oauth-clients/local")
    token = api(
        environ,
        opener,
        "/api/v1/users/token",
        {
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "grant_type": "password",
            "username": environ["PEERTUBE_ROOT_USERNAME"],
            "password": environ["PEERTUBE_ROOT_PASSWORD"],
        },
        form=True,
    )["access_token"]
    created = []
    for member in missing:
        api(
            environ,
            opener,
            "/api/v1/users",
            {
                "username": member["username"],
                "email": member["email"],
                "password": "".join(
                    secrets.choice(PASSWORD_ALPHABET) for _ in range(48)
                ),
                "role": int(member["role"]),
            },
            token=token,
        )
        created.append(member["email"])
    return created


def main(environ, run=subprocess.run, opener=urllib.request.urlopen):
    """Create the missing accounts, hand them to the OIDC plugin, converge the roles.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        opener: ``urllib.request.urlopen`` or a stand-in.
    """
    ranked = ranked_members(
        json.loads(environ["RBAC_MEMBERS"]),
        json.loads(environ["PEERTUBE_RBAC_ROLE_IDS"]),
    )
    missing = json.loads(
        psql(
            environ,
            run,
            "select-members-without-account.sql",
            ["PEERTUBE_RBAC_RANKED"],
            {"PEERTUBE_RBAC_RANKED": json.dumps(ranked)},
        )
    )
    lines = []
    if missing:
        created = create_accounts(environ, opener, missing)
        psql(
            environ,
            run,
            "link-preprovisioned-accounts.sql",
            ["PEERTUBE_OIDC_PLUGIN", "PEERTUBE_ROOT_USERNAME", "PEERTUBE_RBAC_CREATED"],
            {"PEERTUBE_RBAC_CREATED": json.dumps(created)},
        )
        lines += [f"CHANGED {member['username']} created" for member in missing]
    lines += psql(
        environ,
        run,
        "reconcile-roles.sql",
        ["RBAC_MEMBERS", "PEERTUBE_RBAC_ROLE_IDS", "PEERTUBE_OIDC_PLUGIN"],
        {},
    ).splitlines()
    changes = [line for line in lines if line and line != "UNCHANGED"]
    print("\n".join(changes) if changes else "UNCHANGED")


if __name__ == "__main__":
    main(os.environ)
