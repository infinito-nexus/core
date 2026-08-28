# nocheck: mirrored-unit-test - resolves the hub's onboarding or login flow over a live
# WebSocket command channel, reading every credential from the container environment at
# import; nothing here runs without a started Home Assistant
import asyncio
import contextlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:" + os.environ["HA_PORT"]
CLIENT_ID = BASE + "/"
USERNAME = os.environ["HA_USERNAME"]
PASSWORD = os.environ["HA_PASSWORD"]
SERVICE_USERNAME = os.environ["HA_SERVICE_USERNAME"]
SERVICE_PASSWORD = os.environ["HA_SERVICE_PASSWORD"]
SERVICE_NAME = os.environ["HA_SERVICE_NAME"]
SERVICE_GROUP = os.environ["HA_SERVICE_GROUP"]


def request(path, payload=None, token=None, form=False):
    headers = {}
    data = None
    if payload is not None:
        if form:
            data = urllib.parse.urlencode(payload).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(  # noqa: S310 - BASE is the fixed http://localhost loopback of the hub container
        BASE + path, data=data, headers=headers
    )
    with urllib.request.urlopen(  # noqa: S310 - same fixed loopback request object
        req, timeout=30
    ) as response:
        body = response.read().decode()
    return json.loads(body) if body else {}


def onboarding_pending():
    try:
        steps = request("/api/onboarding")
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return False
        raise
    return any(step.get("step") == "user" and not step.get("done") for step in steps)


def access_token_via_onboarding():
    result = request(
        "/api/onboarding/users",
        {
            "name": USERNAME,
            "username": USERNAME,
            "password": PASSWORD,
            "client_id": CLIENT_ID,
            "language": "en",
        },
    )
    token = request(
        "/auth/token",
        {
            "grant_type": "authorization_code",
            "code": result["auth_code"],
            "client_id": CLIENT_ID,
        },
        form=True,
    )["access_token"]
    for step in ("core_config", "analytics", "integration"):
        with contextlib.suppress(urllib.error.HTTPError):
            request("/api/onboarding/" + step, {"client_id": CLIENT_ID}, token=token)
    return token


def access_token_via_login(username, password):
    flow = request(
        "/auth/login_flow",
        {
            "client_id": CLIENT_ID,
            "handler": ["homeassistant", None],
            "redirect_uri": CLIENT_ID,
        },
    )
    step = request(
        "/auth/login_flow/" + flow["flow_id"],
        {
            "client_id": CLIENT_ID,
            "username": username,
            "password": password,
        },
    )
    return request(
        "/auth/token",
        {
            "grant_type": "authorization_code",
            "code": step["result"],
            "client_id": CLIENT_ID,
        },
        form=True,
    )["access_token"]


@contextlib.asynccontextmanager
async def command_channel(access_token):
    """Yield a coroutine that sends one authenticated WebSocket command.

    Args:
        access_token: the access token the channel authenticates with; every
            command runs as that token's user.
    """
    import aiohttp

    async with (
        aiohttp.ClientSession() as session,
        session.ws_connect(BASE + "/api/websocket") as socket,
    ):
        await socket.receive_json()
        await socket.send_json({"type": "auth", "access_token": access_token})
        await socket.receive_json()

        counter = {"id": 0}

        async def command(payload):
            counter["id"] += 1
            await socket.send_json({"id": counter["id"], **payload})
            return await socket.receive_json()

        yield command


async def ensure_service_account(admin_token):
    """Create the non-admin account the MCP long-lived token belongs to.

    A long-lived token always belongs to the user who was logged in when it was
    minted, and Home Assistant has no service-account concept, so the only way
    to keep the deployment's owner account out of every MCP call is to give the
    adapter its own user.
    """
    async with command_channel(admin_token) as command:
        listed = await command({"type": "config/auth/list"})
        existing = [
            entry
            for entry in listed.get("result") or []
            if entry.get("name") == SERVICE_NAME
        ]
        if existing:
            user_id = existing[0]["id"]
        else:
            created = await command(
                {
                    "type": "config/auth/create",
                    "name": SERVICE_NAME,
                    "group_ids": [SERVICE_GROUP],
                }
            )
            if not created.get("success"):
                raise SystemExit("MCP account refused: " + json.dumps(created))
            user_id = created["result"]["user"]["id"]

        if existing:
            regrouped = await command(
                {
                    "type": "config/auth/update",
                    "user_id": user_id,
                    "group_ids": [SERVICE_GROUP],
                }
            )
            if not regrouped.get("success"):
                raise SystemExit("MCP account group refused: " + json.dumps(regrouped))

            changed = await command(
                {
                    "type": "config/auth_provider/homeassistant/admin_change_password",
                    "user_id": user_id,
                    "password": SERVICE_PASSWORD,
                }
            )
            if changed.get("success"):
                return False
            if (changed.get("error") or {}).get("code") != "credentials_not_found":
                raise SystemExit("MCP account password refused: " + json.dumps(changed))

        credentials = await command(
            {
                "type": "config/auth_provider/homeassistant/create",
                "user_id": user_id,
                "username": SERVICE_USERNAME,
                "password": SERVICE_PASSWORD,
            }
        )
        if not credentials.get("success"):
            raise SystemExit("MCP account credentials refused")
    return not existing


async def mint_long_lived_token(access_token, client_name):
    """Return a fresh long-lived token for client_name.

    Home Assistant refuses a second long-lived token under a client_name it
    already knows, so a hub whose volume outlived our token store can only be
    re-provisioned by dropping the stale one first.
    """
    async with command_channel(access_token) as command:
        listed = await command({"type": "auth/refresh_tokens"})
        for entry in listed.get("result") or []:
            if entry.get("client_name") == client_name:
                await command(
                    {
                        "type": "auth/delete_refresh_token",
                        "refresh_token_id": entry["id"],
                    }
                )

        reply = await command(
            {
                "type": "auth/long_lived_access_token",
                "client_name": client_name,
                "lifespan": 3650,
            }
        )
    if not reply.get("success"):
        raise SystemExit("long-lived token refused: " + json.dumps(reply))
    return reply["result"]


def ensure_mcp_entry(token):
    flow = request(
        "/api/config/config_entries/flow", {"handler": "mcp_server"}, token=token
    )
    if flow.get("type") == "abort":
        return False
    request(
        "/api/config/config_entries/flow/" + flow["flow_id"],
        {"llm_hass_api": ["assist"]},
        token=token,
    )
    return True


def main():
    admin_token = (
        access_token_via_onboarding()
        if onboarding_pending()
        else access_token_via_login(USERNAME, PASSWORD)
    )
    asyncio.run(ensure_service_account(admin_token))
    service_token = access_token_via_login(SERVICE_USERNAME, SERVICE_PASSWORD)
    token = asyncio.run(
        mint_long_lived_token(service_token, os.environ["HA_TOKEN_CLIENT_NAME"])
    )
    if ensure_mcp_entry(admin_token):
        print("CHANGED mcp_server")
    print(token)


main()
