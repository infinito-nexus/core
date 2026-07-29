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


def access_token_via_login():
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
        {"client_id": CLIENT_ID, "username": USERNAME, "password": PASSWORD},
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


async def mint_long_lived_token(access_token, client_name):
    import aiohttp

    async with (
        aiohttp.ClientSession() as session,
        session.ws_connect(BASE + "/api/websocket") as socket,
    ):
        await socket.receive_json()
        await socket.send_json({"type": "auth", "access_token": access_token})
        await socket.receive_json()
        await socket.send_json(
            {
                "id": 1,
                "type": "auth/long_lived_access_token",
                "client_name": client_name,
                "lifespan": 3650,
            }
        )
        reply = await socket.receive_json()
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
    access_token = (
        access_token_via_onboarding()
        if onboarding_pending()
        else access_token_via_login()
    )
    token = asyncio.run(
        mint_long_lived_token(access_token, os.environ["HA_TOKEN_CLIENT_NAME"])
    )
    if ensure_mcp_entry(token):
        print("CHANGED mcp_server")
    print(token)


main()
