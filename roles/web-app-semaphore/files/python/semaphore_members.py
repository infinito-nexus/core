"""Args:
sync <roster file>: mirrors the role groups of the roster ``members.py
    settle`` of web-app-keycloak wrote into the workspace's Semaphore project.
    Reads WORKSPACE_SUSPENDED, ``true`` or ``false``, which gives every
    mapped member ``guest`` while it is ``true``, and WORKSPACE,
    SEMAPHORE_API_URL, SEMAPHORE_ADMIN_USERNAME, SEMAPHORE_API_TOKEN_NAME,
    SEMAPHORE_STORE_USERNAME and the SEMAPHORE_DB_HOST, SEMAPHORE_DB_PORT,
    SEMAPHORE_DB, SEMAPHORE_DB_USER and SEMAPHORE_DB_PASS of the Semaphore
    database, where it mints the admin token of the run and deletes it again.
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROLES = {
    "Owner": "task_runner",
    "Admin": "task_runner",
    "Operator": "task_runner",
    "Viewer": "guest",
}
RANK = {"task_runner": 2, "guest": 1}
EDIT_ROLES = ("owner", "manager")
SUSPENDED_ROLE = "guest"
SUSPENDED = {"true": True, "false": False}
TIMEOUT = 30
TOKEN_MINUTES = 15
CONNECTIONS = {"http": http.client.HTTPConnection, "https": http.client.HTTPSConnection}


class SyncError(Exception):
    pass


class Api:
    """Args:
    root: the API root URL, ``http`` or ``https``.
    token: the bearer token.
    connect: ``http.client.HTTPConnection`` or a stand-in; None picks the
        connection class of the root's scheme.
    """

    def __init__(self, root, token, connect=None):
        parts = urlsplit(root)
        if parts.scheme not in CONNECTIONS:
            raise SyncError(f"the API root {root} is no http or https URL")
        self.netloc = parts.netloc
        self.base = parts.path.rstrip("/")
        self.token = token
        self.connect = connect or CONNECTIONS[parts.scheme]

    def call(self, method, path, body=None):
        """Args:
        method: the HTTP method.
        path: the path below the API root.
        body: the JSON body, None to send none.

        Returns:
            The decoded answer, None for an empty one.
        """
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        connection = self.connect(self.netloc, timeout=TIMEOUT)
        try:
            connection.request(method, self.base + path, body=data, headers=headers)
            response = connection.getresponse()
            payload = response.read()
        finally:
            connection.close()
        if response.status >= 400:
            raise SyncError(f"{method} {path}: HTTP {response.status}")
        return json.loads(payload) if payload.strip() else None


def desired_roles(roster, suspended):
    """Args:
    roster: the roster ``members.py settle`` wrote.
    suspended: whether the store suspended the workspace for non-payment.

    Returns:
        ``{keycloak user id: (member, role)}`` of every member whose role
        groups give a Semaphore role; the widest role wins, and every such
        member gets ``guest`` while the workspace is suspended.
    """
    desired = {}
    for member in roster["members"]:
        roles = [ROLES[group] for group in member["groups"] if group in ROLES]
        if roles:
            role = SUSPENDED_ROLE if suspended else max(roles, key=RANK.__getitem__)
            desired[member["id"]] = (member, role)
    return desired


def semaphore_user(api, member, users, log):
    """Args:
    api: the client.
    member: one roster entry.
    users: ``{username: user}`` of every Semaphore account.
    log: sink of the change lines.

    Returns:
        The id of the member's Semaphore account; a member without one gets
        an external account without a password once their address is verified,
        else None.
    """
    user = users.get(member["username"])
    if user is not None:
        return user["id"]
    if not member["emailVerified"]:
        return None
    created = api.call(
        "POST",
        "/users",
        {
            "username": member["username"],
            "name": member["username"],
            "email": member["email"],
            "external": True,
            "admin": False,
            "alert": False,
        },
    )
    users[member["username"]] = created
    log(f"semaphore user {member['id']} created")
    return created["id"]


def sync(api, workspace, project_id, roster, suspended, keep, log):
    """Args:
    api: the client.
    workspace: the workspace id.
    project_id: the workspace project.
    roster: the roster ``members.py settle`` wrote.
    suspended: whether the store suspended the workspace for non-payment.
    keep: the usernames whose membership the sync never touches.
    log: sink of the change lines.

    Raises:
        SyncError: before any write, when the project holds an ``owner`` or
            ``manager`` that is neither a Semaphore admin nor in ``keep``.
    """
    accounts = api.call("GET", "/users")
    users = {user["username"]: user for user in accounts}
    kept = {
        user["id"] for user in accounts if user.get("admin") or user["username"] in keep
    }
    path = f"/project/{project_id}/users"
    current = {m["id"]: m.get("role") for m in api.call("GET", path)}
    editors = sorted(
        user_id
        for user_id, role in current.items()
        if role in EDIT_ROLES and user_id not in kept
    )
    if editors:
        raise SyncError(
            f"workspace {workspace} grants edit rights beyond the store's account: "
            + ", ".join(f"account={user_id}" for user_id in editors)
        )
    wanted = {}
    for member_id, (member, role) in desired_roles(roster, suspended).items():
        user_id = semaphore_user(api, member, users, log)
        if user_id is not None:
            wanted[user_id] = (member_id, role)
    for user_id, (member_id, role) in sorted(wanted.items()):
        if user_id in kept or current.get(user_id) == role:
            continue
        if user_id in current:
            api.call("PUT", f"{path}/{user_id}", {"user_id": user_id, "role": role})
        else:
            api.call("POST", path, {"user_id": user_id, "role": role})
        log(f"semaphore workspace={workspace} user={member_id} role={role}")
    for user_id in sorted(set(current) - set(wanted) - kept):
        api.call("DELETE", f"{path}/{user_id}")
        log(f"semaphore workspace={workspace} account={user_id} role=none")


def remove_role(api, workspace, project_id, username, keep, log):
    """Args:
    api: the client.
    workspace: the workspace id.
    project_id: the workspace project.
    username: the Semaphore username of the leaving member, None when the
        member has none.
    keep: the usernames whose membership this never touches.
    log: sink of the change lines.
    """
    accounts = api.call("GET", "/users")
    user = next((u for u in accounts if u["username"] == username), None)
    if user is None or user.get("admin") or username in keep:
        return
    path = f"/project/{project_id}/users"
    if any(m["id"] == user["id"] for m in api.call("GET", path)):
        api.call("DELETE", f"{path}/{user['id']}")
        log(f"semaphore workspace={workspace} account={user['id']} role=none")


def leaving_username(env):
    """Args:
    env: the task environment with WORKSPACE, WORKSPACE_MEMBER and the
        Keycloak settings of ``workspaces.service_account``.

    Returns:
        The username of the member ``remove`` takes out, None when the
        organization no longer holds the member.
    """
    from workspaces import Workspace, service_account

    workspace = Workspace.load(service_account(env), env["WORKSPACE"], "remove")
    member = (workspace.members if workspace else {}).get(env["WORKSPACE_MEMBER"])
    return member.get("username") if member else None


def connect(env):
    """Args:
    env: the task environment with the SEMAPHORE_DB_* settings.

    Returns:
        A connection to the Semaphore database.
    """
    import psycopg2

    return psycopg2.connect(
        host=env["SEMAPHORE_DB_HOST"],
        port=env["SEMAPHORE_DB_PORT"],
        dbname=env["SEMAPHORE_DB"],
        user=env["SEMAPHORE_DB_USER"],
        password=env["SEMAPHORE_DB_PASS"],
    )


def mint(connection, env):
    """Args:
    connection: the database connection.
    env: the task environment with SEMAPHORE_ADMIN_USERNAME and SEMAPHORE_API_TOKEN_NAME.

    Returns:
        A short-lived admin token, which :func:`revoke` deletes.
    """
    with connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.user__token (id, created, expired, user_id, expires_at, name) "
            "SELECT left(replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', ''), 44), "
            "now(), FALSE, account.id, now() + make_interval(mins => %s), %s "
            'FROM public."user" AS account WHERE account.username = %s AND account.admin RETURNING id',
            (
                TOKEN_MINUTES,
                env["SEMAPHORE_API_TOKEN_NAME"],
                env["SEMAPHORE_ADMIN_USERNAME"],
            ),
        )
        row = cursor.fetchone()
    if row is None:
        raise SyncError("the Semaphore admin of the token does not exist")
    return row[0]


def revoke(connection, token):
    """Args:
    connection: the database connection.
    token: what :func:`mint` returned.
    """
    with connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM public.user__token WHERE id = %s", (token,))


def workspace_project(connection, workspace):
    """Args:
    connection: the database connection.
    workspace: the workspace id.

    Returns:
        The id of the project the workspace's runner row names.
    """
    with connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT project_id FROM public.runner WHERE name = %s AND project_id IS NOT NULL",
            (f"ws-{workspace}",),
        )
        row = cursor.fetchone()
    if row is None:
        raise SyncError(f"no runner names the project of ws-{workspace}")
    return row[0]


def main(argv, env):
    """Args:
    argv: the command line after the script name.
    env: the task environment.

    Returns:
        The exit code.
    """
    if argv[:1] == ["sync"] and len(argv) == 2:
        suspended = SUSPENDED.get(env.get("WORKSPACE_SUSPENDED"))
        if suspended is None:
            print(
                "semaphore_members.py: WORKSPACE_SUSPENDED is missing or malformed",
                file=sys.stderr,
            )
            return 2
        roster = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        if roster["workspace"] != env["WORKSPACE"]:
            print(
                "semaphore_members.py: the roster names another workspace",
                file=sys.stderr,
            )
            return 1
    elif argv != ["remove"]:
        print(
            "semaphore_members.py: expects sync <roster file> or remove",
            file=sys.stderr,
        )
        return 2
    keep = {env["SEMAPHORE_STORE_USERNAME"]}
    connection = connect(env)
    try:
        token = mint(connection, env)
        try:
            api = Api(env["SEMAPHORE_API_URL"], token)
            project_id = workspace_project(connection, env["WORKSPACE"])
            if argv[0] == "sync":
                sync(api, env["WORKSPACE"], project_id, roster, suspended, keep, print)
            else:
                remove_role(
                    api,
                    env["WORKSPACE"],
                    project_id,
                    leaving_username(env),
                    keep,
                    print,
                )
        finally:
            revoke(connection, token)
    except SyncError as error:
        print(f"semaphore_members.py: {error}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


def _terminate(signum, _frame):
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    raise SystemExit(main(sys.argv[1:], dict(os.environ)))
