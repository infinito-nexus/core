"""Give the MCP adapter a read-only Jellyfin user and print its access token.

Jellyfin mints every token itself, so the deployment cannot pin one. What it
can pin is the user: the password is a deployment credential, the policy is
written explicitly, and the token is captured from the authentication that
follows.

An API key is not an option here. Jellyfin resolves every API key to the
administrator role, so the least-privileged identity that still reads the
contracted endpoints is a user token.

Prints the access token on stdout, prefixed by CHANGED or UNCHANGED.

Environment:
    JELLYFIN_BASE:           server base URL.
    JELLYFIN_ADMIN_USER:     administrator to act as.
    JELLYFIN_ADMIN_PASSWORD: that administrator's password.
    MCP_USER:                username to converge.
    MCP_PASSWORD:            password to pin on it.
    MCP_DEVICE_ID:           stable device id, so re-runs reuse one session.
    MCP_CURRENT_TOKEN:       token the adapter holds today, or "" for none.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ["JELLYFIN_BASE"].rstrip("/")
ADMIN_USER = os.environ["JELLYFIN_ADMIN_USER"]
ADMIN_PASSWORD = os.environ["JELLYFIN_ADMIN_PASSWORD"]
MCP_USER = os.environ["MCP_USER"]
MCP_PASSWORD = os.environ["MCP_PASSWORD"]
DEVICE_ID = os.environ["MCP_DEVICE_ID"]
CURRENT_TOKEN = os.environ.get("MCP_CURRENT_TOKEN", "").strip()

TIMEOUT = 30
CLIENT = (
    'MediaBrowser Client="infinito", Device="ansible", '
    f'DeviceId="{DEVICE_ID}", Version="1.0.0"'
)

READ_ONLY_POLICY = {
    "IsAdministrator": False,
    "IsHidden": True,
    "IsDisabled": False,
    "EnableAllFolders": True,
    "EnableRemoteAccess": True,
    "EnableMediaPlayback": False,
    "EnableContentDeletion": False,
    "EnableContentDownloading": False,
    "EnableCollectionManagement": False,
    "EnableSubtitleManagement": False,
    "EnableLyricManagement": False,
    "EnableLiveTvManagement": False,
    "EnableLiveTvAccess": False,
    "EnableRemoteControlOfOtherUsers": False,
    "EnableSharedDeviceControl": False,
    "EnableMediaConversion": False,
    "EnableAudioPlaybackTranscoding": False,
    "EnableVideoPlaybackTranscoding": False,
    "EnablePlaybackRemuxing": False,
    "EnablePublicSharing": False,
    "EnableSyncTranscoding": False,
    "EnableUserPreferenceAccess": False,
    "AuthenticationProviderId": (
        "Jellyfin.Server.Implementations.Users.DefaultAuthenticationProvider"
    ),
    "PasswordResetProviderId": (
        "Jellyfin.Server.Implementations.Users.DefaultPasswordResetProvider"
    ),
}


TRANSIENT_STATUS = frozenset({0, 429, 502, 503, 504})


def fail(message, status=None):
    """Abort the run, marking only a terminal cause as REJECTED.

    Args:
        message: what went wrong.
        status: the HTTP status that caused it, when there was one.
    """
    marker = "PENDING" if status in TRANSIENT_STATUS else "REJECTED"
    sys.stderr.write(f"{marker} {message}\n")
    sys.exit(1)


def call(method, path, payload=None, token=None):
    """Return ``(status, parsed body)`` of one Jellyfin API call.

    Args:
        method: HTTP method.
        path: path below the server base.
        payload: JSON body, or None.
        token: access token to authenticate with, or None for the client header.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method)  # noqa: S310 fixed internal http origin
    request.add_header("Accept", "application/json")
    request.add_header(
        "Authorization", f'{CLIENT}, Token="{token}"' if token else CLIENT
    )
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 fixed internal http origin
            body = response.read()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")
    except OSError as error:
        return 0, f"unreachable: {error}"


def admin_token():
    status, body = call(
        "POST",
        "/Users/AuthenticateByName",
        {"Username": ADMIN_USER, "Pw": ADMIN_PASSWORD},
    )
    if status != 200 or not isinstance(body, dict):
        fail(
            f"authenticating {ADMIN_USER} answered {status}: {str(body)[:200]}", status
        )
    return body["AccessToken"]


def ensure_user(token):
    status, body = call("GET", "/Users", token=token)
    if status != 200:
        fail(f"listing users answered {status}: {str(body)[:200]}", status)

    for user in body or []:
        if user.get("Name") == MCP_USER:
            return user["Id"], False

    status, body = call(
        "POST", "/Users/New", {"Name": MCP_USER, "Password": MCP_PASSWORD}, token=token
    )
    if status not in (200, 204) or not isinstance(body, dict):
        fail(f"creating {MCP_USER} answered {status}: {str(body)[:200]}", status)
    return body["Id"], True


def set_password(token, user_id):
    """Converge the inventory password onto a user that already exists.

    Args:
        token: an administrator access token; the server skips the
            current-password check only for an admin acting on another user.
        user_id: the target user's id, passed as a query parameter because
            omitting it retargets the caller's own account.
    """
    status, body = call(
        "POST",
        f"/Users/Password?userId={user_id}",
        {"NewPw": MCP_PASSWORD, "ResetPassword": False},
        token=token,
    )
    if status not in (200, 204):
        fail(
            f"setting the password of {MCP_USER} answered {status}: {str(body)[:200]}",
            status,
        )


def main():
    status, body = call(
        "POST", "/Users/AuthenticateByName", {"Username": MCP_USER, "Pw": MCP_PASSWORD}
    )
    if status == 200 and isinstance(body, dict):
        if CURRENT_TOKEN:
            probe, _ = call("GET", "/System/Info", token=CURRENT_TOKEN)
            if probe == 200:
                print("UNCHANGED")
                print(CURRENT_TOKEN)
                return
        print("CHANGED")
        print(body["AccessToken"])
        return

    token = admin_token()
    user_id, _created = ensure_user(token)

    status, body = call(
        "POST", f"/Users/{user_id}/Policy", READ_ONLY_POLICY, token=token
    )
    if status not in (200, 204):
        fail(f"restricting {MCP_USER} answered {status}: {str(body)[:200]}", status)

    set_password(token, user_id)

    status, body = call(
        "POST",
        "/Users/AuthenticateByName",
        {"Username": MCP_USER, "Pw": MCP_PASSWORD},
    )
    if status != 200 or not isinstance(body, dict):
        fail(f"authenticating {MCP_USER} answered {status}: {str(body)[:200]}", status)

    print("CHANGED")
    print(body["AccessToken"])


if __name__ == "__main__":
    main()
