"""Push the directory photo of every Jellyfin account as its profile image.

Files:
    state.json: digest of the photo pushed per account, in the working directory.

Environment:
    RBAC_SYNC_LDAP: JSON directory settings the runner exports.
    LDAP_PHOTO_ATTRIBUTE: attribute that holds the photo.
    JELLYFIN_API: Jellyfin's local URL on the node.
    JELLYFIN_API_CLIENT: value of the ``X-Emby-Authorization`` header.
    JELLYFIN_ADMIN_USERNAME, JELLYFIN_ADMIN_PASSWORD: the local administrator.

Output:
    One ``CHANGED <username> photo`` line per pushed photo, else ``UNCHANGED``.
"""

import base64
import hashlib
import json
import os
import urllib.request
from pathlib import Path

from ldap_client import SCOPE_ONE_LEVEL, Connection, present, raw

STATE_FILE = Path("state.json")


def directory_photos(environ, connect):
    """Return ``{username: photo octets}`` of every account that has a photo.

    Args:
        environ: the process environment.
        connect: ``ldap_client.Connection`` or a stand-in.
    """
    ldap = json.loads(environ["RBAC_SYNC_LDAP"])
    login = ldap["attributes"]["id"]
    photo = environ["LDAP_PHOTO_ATTRIBUTE"]
    connection = connect(ldap["uri"])
    try:
        entries = connection.search(
            ldap["users_dn"], SCOPE_ONE_LEVEL, present(photo), [login, photo]
        )
    finally:
        connection.close()
    photos = {}
    for _, values in entries:
        logins = values.get(login.lower())
        images = values.get(photo.lower())
        if logins and images:
            photos[logins[0]] = raw(images[0])
    return photos


def api(environ, opener, path, method, body, headers):
    """Return the raw answer of one Jellyfin API request.

    Args:
        environ: the process environment.
        opener: ``urllib.request.urlopen`` or a stand-in.
        path: path below the API URL.
        method: the HTTP method.
        body: the request body, or None.
        headers: the request headers.
    """
    request = urllib.request.Request(  # noqa: S310 - JELLYFIN_API is the node-local Jellyfin port
        environ["JELLYFIN_API"] + path, data=body, headers=headers, method=method
    )
    with opener(request, timeout=60) as response:
        return response.read()


def main(
    environ, opener=urllib.request.urlopen, connect=Connection, state_file=STATE_FILE
):
    """Push every changed directory photo and print the result.

    Args:
        environ: the process environment.
        opener: ``urllib.request.urlopen`` or a stand-in.
        connect: ``ldap_client.Connection`` or a stand-in.
        state_file: where the pushed digests are remembered.
    """
    photos = directory_photos(environ, connect)
    pushed = (
        json.loads(state_file.read_text(encoding="utf-8"))
        if state_file.exists()
        else {}
    )
    client = {
        "X-Emby-Authorization": environ["JELLYFIN_API_CLIENT"],
        "Content-Type": "application/json",
    }
    session = json.loads(
        api(
            environ,
            opener,
            "/Users/AuthenticateByName",
            "POST",
            json.dumps(
                {
                    "Username": environ["JELLYFIN_ADMIN_USERNAME"],
                    "Pw": environ["JELLYFIN_ADMIN_PASSWORD"],
                }
            ).encode(),
            client,
        )
    )
    authorization = {"Authorization": f'MediaBrowser Token="{session["AccessToken"]}"'}
    accounts = {
        user["Name"]: user["Id"]
        for user in json.loads(
            api(environ, opener, "/Users", "GET", None, authorization)
        )
    }
    lines = []
    for username, image in sorted(photos.items()):
        digest = hashlib.sha256(image).hexdigest()
        if username not in accounts or pushed.get(username) == digest:
            continue
        api(
            environ,
            opener,
            f"/UserImage?userId={accounts[username]}",
            "POST",
            base64.b64encode(image),
            {**authorization, "Content-Type": "image/jpeg"},
        )
        pushed[username] = digest
        lines.append(f"CHANGED {username} photo")
    state_file.write_text(json.dumps(pushed, sort_keys=True), encoding="utf-8")
    print("\n".join(lines) or "UNCHANGED")


if __name__ == "__main__":
    main(os.environ)
