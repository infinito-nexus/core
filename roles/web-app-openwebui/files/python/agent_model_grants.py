"""
Environment:
    OPENWEBUI_BASE:            in-container Open WebUI base URL.
    OPENWEBUI_ADMIN_EMAIL:     administrator to take or mint an API key for.
    OPENWEBUI_ADMIN_NAME:      its display name when it has to be created.
    OPENWEBUI_ADMIN_PASSWORD:  its password when it has to be created.
    OPENWEBUI_GATEWAY_URL:     LiteLLM base URL whose models become public, except the
                               ones its /v1/model/info declares in an UNGRANTED_MODES
                               mode; empty skips them.
    OPENWEBUI_GATEWAY_KEY:     Open WebUI's own gateway key.
    OPENWEBUI_AGENT_MODELS:    JSON model id -> group name.
    OPENWEBUI_GATEWAY_FAILED_RC: exit code of a gateway the run cannot list, which
                               the deploy does not retry.
"""

import asyncio
import json
import os
import secrets
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/app/backend")

BASE = os.environ["OPENWEBUI_BASE"].rstrip("/")
ADMIN_EMAIL = os.environ["OPENWEBUI_ADMIN_EMAIL"]
ADMIN_NAME = os.environ["OPENWEBUI_ADMIN_NAME"]
ADMIN_PASSWORD = os.environ["OPENWEBUI_ADMIN_PASSWORD"]
GATEWAY_URL = os.environ["OPENWEBUI_GATEWAY_URL"].rstrip("/")
GATEWAY_KEY = os.environ["OPENWEBUI_GATEWAY_KEY"]
AGENT_MODELS = json.loads(os.environ["OPENWEBUI_AGENT_MODELS"])
GATEWAY_FAILED_RC = int(os.environ["OPENWEBUI_GATEWAY_FAILED_RC"])
PUBLIC = [{"principal_type": "user", "principal_id": "*", "permission": "read"}]
UNGRANTED_MODES = ("audio_transcription", "audio_speech", "embedding")


async def resolve_api_key():
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


def call(url, key, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - fixed http:// bases from the environment, no user-supplied scheme
        url, data=data, method="POST" if data else "GET"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed http:// bases from the environment, no user-supplied scheme
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def gateway_listing(path):
    """
    Returns:
        The ``data`` list the gateway answers ``path`` with. An unreachable gateway
        or any other answer than 200 ends the run with GATEWAY_FAILED_RC and the
        reason on stderr, without the answer body.
    """
    url = f"{GATEWAY_URL}{path}"
    try:
        status, body = call(url, GATEWAY_KEY)
    except OSError as error:
        print(f"FAILED: the gateway at {url} is unreachable: {error}", file=sys.stderr)
        sys.exit(GATEWAY_FAILED_RC)
    if status != 200:
        print(f"FAILED: the gateway at {url} answered HTTP {status}", file=sys.stderr)
        sys.exit(GATEWAY_FAILED_RC)
    return body.get("data") or []


def gateway_grants():
    """
    Returns:
        gateway model id -> access grants: PUBLIC, or none for a model whose
        model_info mode is in UNGRANTED_MODES.
    """
    if not GATEWAY_URL:
        return {}
    models = [item["id"] for item in gateway_listing("/v1/models")]
    ungranted = {
        entry["model_name"]
        for entry in (gateway_listing("/v1/model/info") if models else [])
        if (entry.get("model_info") or {}).get("mode") in UNGRANTED_MODES
    }
    return {model_id: [] if model_id in ungranted else PUBLIC for model_id in models}


def group_id(key, name):
    status, body = call(f"{BASE}/api/v1/groups/", key)
    if status != 200:
        sys.exit(f"FAILED listing groups: {status} {body}")
    matches = [group for group in body if group.get("name") == name]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} groups named {name}, refusing to guess")
    if matches:
        return matches[0]["id"]
    status, body = call(
        f"{BASE}/api/v1/groups/create",
        key,
        {"name": name, "description": "Per-user agent access"},
    )
    if status != 200:
        sys.exit(f"FAILED creating group {name}: {status} {body}")
    return body["id"]


async def _stored_grants(model_id):
    from open_webui.models.access_grants import AccessGrants

    grants = await AccessGrants.get_grants_by_resource("model", model_id)
    return sorted(
        (grant.principal_type, grant.principal_id, grant.permission)
        for grant in grants or []
    )


def current_grants(model_id):
    return asyncio.run(_stored_grants(model_id))


def ensure_grants(key, model_id, grants):
    wanted = sorted(
        (g["principal_type"], g["principal_id"], g["permission"]) for g in grants
    )
    if current_grants(model_id) == wanted:
        return False
    status, body = call(
        f"{BASE}/api/v1/models/model/access/update",
        key,
        {"id": model_id, "name": model_id, "access_grants": grants},
    )
    if status != 200:
        sys.exit(f"FAILED granting {model_id}: {status} {body}")
    if current_grants(model_id) != wanted:
        sys.exit(f"FAILED: {model_id} does not carry {wanted} after the write")
    return True


def provision(key):
    changed = False
    for model_id, grants in gateway_grants().items():
        if model_id not in AGENT_MODELS:
            changed |= ensure_grants(key, model_id, grants)
    for model_id, group_name in AGENT_MODELS.items():
        grant = {
            "principal_type": "group",
            "principal_id": group_id(key, group_name),
            "permission": "read",
        }
        changed |= ensure_grants(key, model_id, [grant])
    return changed


if __name__ == "__main__":
    admin_id, api_key, minted = asyncio.run(resolve_api_key())
    try:
        result = provision(api_key)
    finally:
        if minted:
            asyncio.run(drop_api_key(admin_id))
    print("CHANGED" if result else "OK")
