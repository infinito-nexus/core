# nocheck: mirrored-unit-test - resolves the hub's onboarding or login flow over a live
# WebSocket command channel, reading every credential from the container environment at
# import; nothing here runs without a started Home Assistant
"""Onboard the hub or sign in as its owner, then provision its MCP surface.

Environment:
    HA_PORT: the hub's internal port.
    HA_USERNAME, HA_PASSWORD: the owner account.
    HA_OWNER_ONLY: "1" ends the run after the owner step, which prints
        "CHANGED owner" when it created the owner or closed an onboarding step.
    HA_LOCATION_NAME: name the onboarding gives the hub; unset or empty keeps
        the name Home Assistant picks.
    HA_SERVICE_USERNAME, HA_SERVICE_PASSWORD, HA_SERVICE_NAME, HA_SERVICE_GROUP,
    HA_TOKEN_CLIENT_NAME: the MCP account and the client name of its token;
        read unless HA_OWNER_ONLY is "1".
"""

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
OWNER_ONLY = os.environ.get("HA_OWNER_ONLY") == "1"
LOCATION_NAME = os.environ.get("HA_LOCATION_NAME")
if not OWNER_ONLY:
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


def open_onboarding_steps():
    """Return the names of the onboarding steps the hub still waits for."""
    try:
        steps = request("/api/onboarding")
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return []
        raise
    return [step["step"] for step in steps if not step["done"]]


def onboarding_pending():
    return "user" in open_onboarding_steps()


def access_token(code):
    """Exchange an authorization code for an access token.

    Args:
        code: the authorization code an onboarding or login step returned.
    """
    return request(
        "/auth/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
        },
        form=True,
    )["access_token"]


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
    token = access_token(result["auth_code"])
    if LOCATION_NAME:
        asyncio.run(name_location(token))
    return token


def finish_onboarding(token):
    """Close every onboarding step after the owner step that is still open.

    The index page keeps redirecting to the onboarding wizard until all steps
    are done, and the integration step refuses a request without redirect_uri.

    Args:
        token: an access token of the owner.

    Returns:
        Whether a step was closed.
    """
    steps = [step for step in open_onboarding_steps() if step != "user"]
    for step in steps:
        request(
            "/api/onboarding/" + step,
            {"client_id": CLIENT_ID, "redirect_uri": CLIENT_ID},
            token=token,
        )
    return bool(steps)


def authorization_code_via_login(username, password):
    """Sign in through the login flow without minting a refresh token.

    Args:
        username: the account to sign in as.
        password: its password.

    Returns:
        The authorization code of the accepted login.
    """
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
    if step.get("type") != "create_entry":
        raise SystemExit(
            f"home assistant refused the login of {username}: {json.dumps(step)}"
        )
    return step["result"]


def access_token_via_login(username, password):
    return access_token(authorization_code_via_login(username, password))


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


async def name_location(access_token):
    """Give the hub the configured location name.

    Args:
        access_token: an access token of the owner.
    """
    async with command_channel(access_token) as command:
        named = await command(
            {"type": "config/core/update", "location_name": LOCATION_NAME}
        )
    if not named.get("success"):
        raise SystemExit("location name refused: " + json.dumps(named))


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
    created = onboarding_pending()
    if OWNER_ONLY and not open_onboarding_steps():
        authorization_code_via_login(USERNAME, PASSWORD)
        return
    admin_token = (
        access_token_via_onboarding()
        if created
        else access_token_via_login(USERNAME, PASSWORD)
    )
    finished = finish_onboarding(admin_token)
    if OWNER_ONLY:
        if created or finished:
            print("CHANGED owner")
        return
    asyncio.run(ensure_service_account(admin_token))
    service_token = access_token_via_login(SERVICE_USERNAME, SERVICE_PASSWORD)
    token = asyncio.run(
        mint_long_lived_token(service_token, os.environ["HA_TOKEN_CLIENT_NAME"])
    )
    if ensure_mcp_entry(admin_token):
        print("CHANGED mcp_server")
    print(token)


main()
