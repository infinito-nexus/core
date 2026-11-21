"""Align the hub accounts the directory sign-in created with the role groups.

Environment:
    HA_PORT: the hub's internal port.
    HA_USERNAME, HA_PASSWORD: the owner account the alignment signs in with.
    HA_AUTH_STORE: path of the hub's auth store.
    HA_ADMIN_MEMBERS, HA_USER_MEMBERS: JSON lists of the login names in the
        administrator and the user role group.

Output:
    One ``CHANGED <user id> <fields>`` line per account it regrouped,
    re-enabled or disabled, else ``UNCHANGED``.
"""

import asyncio
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

PROVIDER_TYPE = "command_line"
ADMIN_GROUP_ID = "system-admin"
USER_GROUP_ID = "system-users"


def plan(store, administrators, users):
    """Return the updates that bring the directory accounts in line with the role groups.

    Only accounts whose every credential belongs to the directory sign-in are
    touched, so the owner, the MCP account and every other local account keep
    their state.

    Args:
        store: the parsed auth store of the hub.
        administrators: login names in the administrator role group.
        users: login names in the user role group.

    Returns:
        ``config/auth/update`` payloads without their ``type``, one per account that differs.
    """
    data = store["data"]
    logins = {}
    foreign = set()
    for credential in data["credentials"]:
        if credential["auth_provider_type"] == PROVIDER_TYPE:
            logins.setdefault(credential["user_id"], set()).add(
                credential["data"]["username"]
            )
        else:
            foreign.add(credential["user_id"])

    updates = []
    for user in data["users"]:
        user_id = user["id"]
        if (
            user_id not in logins
            or user_id in foreign
            or user["is_owner"]
            or user["system_generated"]
        ):
            continue
        names = logins[user_id]
        wanted = {"is_active": False}
        if names & set(administrators):
            wanted = {"group_ids": [ADMIN_GROUP_ID], "is_active": True}
        elif names & set(users):
            wanted = {"group_ids": [USER_GROUP_ID], "is_active": True}
        changed = {key: value for key, value in wanted.items() if user[key] != value}
        if changed:
            updates.append({"user_id": user_id, **changed})
    return updates


def read_store(path):
    """Return the parsed auth store; a hub that never saved one holds no directory account.

    Args:
        path: path of the auth store.
    """
    try:
        content = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"data": {"users": [], "credentials": []}}
    return json.loads(content)


def owner_token(base, username, password):
    """Sign in through the local provider and return an access token.

    Args:
        base: the hub's loopback URL.
        username: the owner account.
        password: its password.
    """

    def post(path, payload, form):
        body = (
            urllib.parse.urlencode(payload).encode()
            if form
            else json.dumps(payload).encode()
        )
        kind = "application/x-www-form-urlencoded" if form else "application/json"
        req = urllib.request.Request(  # noqa: S310 - base is the fixed http://localhost loopback of the hub container
            base + path, data=body, headers={"Content-Type": kind}
        )
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - same fixed loopback request object
            return json.loads(response.read().decode())

    client_id = base + "/"
    flow = post(
        "/auth/login_flow",
        {
            "client_id": client_id,
            "handler": ["homeassistant", None],
            "redirect_uri": client_id,
        },
        form=False,
    )
    step = post(
        "/auth/login_flow/" + flow["flow_id"],
        {"client_id": client_id, "username": username, "password": password},
        form=False,
    )
    if step.get("type") != "create_entry":
        raise SystemExit(f"home assistant refused the login of {username}")
    token = post(
        "/auth/token",
        {
            "grant_type": "authorization_code",
            "code": step["result"],
            "client_id": client_id,
        },
        form=True,
    )
    return token["access_token"]


async def apply(base, token, updates):
    """Send every update over one authenticated WebSocket command channel.

    Args:
        base: the hub's loopback URL.
        token: an access token of the owner.
        updates: the payloads ``plan`` returned.
    """
    import aiohttp

    async with (
        aiohttp.ClientSession() as session,
        session.ws_connect(base + "/api/websocket") as socket,
    ):
        await socket.receive_json()
        await socket.send_json({"type": "auth", "access_token": token})
        await socket.receive_json()
        for message_id, update in enumerate(updates, start=1):
            await socket.send_json(
                {"id": message_id, "type": "config/auth/update", **update}
            )
            reply = await socket.receive_json()
            if not reply.get("success"):
                raise SystemExit("account update refused: " + json.dumps(reply))


def main(environ):
    """Align the directory accounts and print one line per change.

    Args:
        environ: the process environment.
    """
    updates = plan(
        read_store(environ["HA_AUTH_STORE"]),
        json.loads(environ["HA_ADMIN_MEMBERS"]),
        json.loads(environ["HA_USER_MEMBERS"]),
    )
    if not updates:
        print("UNCHANGED")
        return
    base = "http://localhost:" + environ["HA_PORT"]
    token = owner_token(base, environ["HA_USERNAME"], environ["HA_PASSWORD"])
    asyncio.run(apply(base, token, updates))
    for update in updates:
        fields = {key: value for key, value in update.items() if key != "user_id"}
        print(f"CHANGED {update['user_id']} {json.dumps(fields, sort_keys=True)}")


if __name__ == "__main__":
    main(os.environ)
