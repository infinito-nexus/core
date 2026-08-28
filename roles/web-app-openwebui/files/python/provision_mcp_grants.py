import asyncio
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from copy import deepcopy

sys.path.insert(0, "/app/backend")

BASE = os.environ.get("OPENWEBUI_BASE", "").rstrip("/")
GROUPS = json.loads(os.environ.get("OPENWEBUI_MCP_GROUPS", "{}"))
MEMBERS = json.loads(os.environ.get("OPENWEBUI_MCP_MEMBERS", "{}"))

DECLARED = json.loads(os.environ.get("OPENWEBUI_MCP_CONNECTIONS", "[]"))
ADMIN_EMAIL = os.environ.get("OPENWEBUI_ADMIN_EMAIL", "")
ADMIN_NAME = os.environ.get("OPENWEBUI_ADMIN_NAME", "administrator")
ADMIN_PASSWORD = os.environ.get("OPENWEBUI_ADMIN_PASSWORD", "")


async def resolve_api_key():
    """Return an administrator API key and whether this run minted it.

    Signup cannot be used: Open WebUI only promotes a signup to admin while it
    is the very first user, and disables signup afterwards. So the key is taken
    from an existing administrator, and only a deployment with no users at all
    creates one. A key minted here is removed again once the run is done, so the
    deploy leaves no standing admin credential behind.
    """
    from open_webui.models.auths import Auths
    from open_webui.models.users import Users
    from open_webui.utils.auth import get_password_hash

    existing = (await Users.get_users()).get("users") or []
    admin = next((user for user in existing if user.role == "admin"), None)
    if admin is None:
        admin = await Auths.insert_new_auth(
            email=ADMIN_EMAIL.lower(),
            password=await get_password_hash(ADMIN_PASSWORD),
            name=ADMIN_NAME,
            role="admin",
        )
    if admin is None:
        sys.exit("FAILED: no administrator exists and one could not be created")

    key = await Users.get_user_api_key_by_id(admin.id)
    if key:
        return admin.id, key, False

    key = f"sk-{secrets.token_hex(32)}"
    if not await Users.update_user_api_key_by_id(admin.id, key):
        sys.exit(f"FAILED: could not mint an API key for {admin.id}")
    return admin.id, key, True


async def drop_api_key(user_id):
    from open_webui.models.users import Users

    await Users.delete_user_api_key_by_id(user_id)


def call(path, key, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - fixed http:// base from OPENWEBUI_BASE, no user-supplied scheme
        f"{BASE}{path}",
        data=data,
        method="POST" if data else "GET",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed http:// base from OPENWEBUI_BASE, no user-supplied scheme
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def group_id(key, name):
    status, body = call("/api/v1/groups/", key)
    if status != 200:
        sys.exit(f"FAILED listing groups: {status} {body}")

    matches = [group for group in body if group.get("name") == name]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} groups named {name}, refusing to guess")
    if matches:
        return matches[0]["id"], matches[0]

    status, body = call(
        "/api/v1/groups/create",
        key,
        {"name": name, "description": "MCP tool server access"},
    )
    if status != 200:
        sys.exit(f"FAILED creating group {name}: {status} {body}")
    return body["id"], body


async def user_ids_for(members):
    """Return the Open WebUI ids of the users named in ``members``.

    Args:
        members: ``[{"username": ..., "email": ...}, ...]`` as granted by the
            declarative configuration.

    A member Open WebUI has never seen has no id yet, so it is skipped: the
    OIDC login that creates the account also carries the groups claim.
    """
    if not members:
        return []

    from open_webui.models.users import Users

    existing = (await Users.get_users()).get("users") or []
    by_email = {str(u.email or "").lower(): u.id for u in existing}
    by_name = {str(u.name or "").lower(): u.id for u in existing}

    ids = []
    for member in members:
        email = str(member.get("email") or "").lower()
        name = str(member.get("username") or "").lower()
        found = by_email.get(email) or by_name.get(name)
        if found and found not in ids:
            ids.append(found)
    return ids


def reconcile_members(key, group, member_ids):
    """Set a group's members to exactly ``member_ids``.

    Args:
        key: the administrator API key.
        group: the group as the API returned it.
        member_ids: the Open WebUI user ids that should remain.

    The OIDC groups claim cannot do this on its own: Open WebUI drops a stale
    membership only while the claim is non-empty, so a user who loses their
    last group keeps the old one until some later login carries another. An
    explicit write is what makes removing the last grant revoke access.
    """
    if sorted(group.get("user_ids") or []) == sorted(member_ids):
        return False
    status, body = call(
        f"/api/v1/groups/id/{group['id']}/update",
        key,
        {
            "name": group.get("name"),
            "description": group.get("description") or "MCP tool server access",
            "permissions": group.get("permissions"),
            "user_ids": member_ids,
        },
    )
    if status != 200:
        sys.exit(f"FAILED updating group {group.get('name')}: {status} {body}")
    return True


def grant(key):
    status, body = call("/api/v1/configs/tool_servers", key)
    if status != 200:
        sys.exit(f"FAILED reading tool servers: {status} {body}")

    connections = body.get("TOOL_SERVER_CONNECTIONS") or []
    original = deepcopy(connections)
    declared = {(entry.get("info") or {}).get("id"): entry for entry in DECLARED}
    known = {
        (connection.get("info") or {}).get("id")
        for connection in connections
        if connection.get("type") == "mcp"
    }
    connections += [
        deepcopy(entry)
        for server_id, entry in declared.items()
        if server_id not in known
    ]
    wanted = {}
    members_changed = False
    for connection in connections:
        server_id = (connection.get("info") or {}).get("id")
        name = GROUPS.get(server_id)
        if connection.get("type") != "mcp" or not name:
            continue
        source = declared.get(server_id) or {}
        for field in ("url", "path", "key", "auth_type"):
            if field in source:
                connection[field] = source[field]
        wanted[server_id], group = group_id(key, name)
        member_ids = asyncio.run(user_ids_for(MEMBERS.get(server_id) or []))
        members_changed |= reconcile_members(key, group, member_ids)
        config = connection.setdefault("config", {})
        config["access_grants"] = [
            {
                "principal_type": "group",
                "principal_id": wanted[server_id],
                "permission": "read",
            }
        ]
        config["enable"] = True

    if connections == original:
        return wanted, members_changed

    status, body = call(
        "/api/v1/configs/tool_servers", key, {"TOOL_SERVER_CONNECTIONS": connections}
    )
    if status != 200:
        sys.exit(f"FAILED writing tool servers: {status} {body}")

    status, body = call("/api/v1/configs/tool_servers", key)
    if status != 200:
        sys.exit(f"FAILED re-reading tool servers: {status} {body}")

    written = body.get("TOOL_SERVER_CONNECTIONS") or []
    missing = {(entry.get("info") or {}).get("id") for entry in connections} - {
        (entry.get("info") or {}).get("id") for entry in written
    }
    if missing:
        sys.exit(f"FAILED: the write lost {sorted(missing)}")

    for connection in written:
        server_id = (connection.get("info") or {}).get("id")
        if server_id not in wanted:
            continue
        config = connection.get("config") or {}
        grants = config.get("access_grants") or []
        ids = [
            g.get("principal_id") for g in grants if g.get("principal_type") == "group"
        ]
        if ids != [wanted[server_id]]:
            sys.exit(f"FAILED: {server_id} carries {grants} instead of one group grant")
        if not config.get("enable"):
            sys.exit(f"FAILED: {server_id} stayed disabled after the grant was written")

    return wanted, True


if __name__ == "__main__":
    admin_id, api_key, minted = asyncio.run(resolve_api_key())
    try:
        resolved, changed = grant(api_key)
    finally:
        if minted:
            asyncio.run(drop_api_key(admin_id))
    if GROUPS and not resolved:
        sys.exit(f"FAILED: none of the {len(GROUPS)} declared MCP servers was granted")

    print(f"{'CHANGED' if changed else 'OK'} granted={len(resolved)}")
    print(json.dumps(resolved))
