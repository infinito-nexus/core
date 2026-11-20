"""Push the directory photo of every Jellyfin account as its profile image.

Files:
    state.json: digest of the photo pushed per account, in the working directory.

Environment:
    RBAC_SYNC_MEMBERS_FILE: JSON ``{"@users:<photo attribute>": [members]}`` the
        runner hands over, every account that holds a photo with the photo
        base64-encoded under ``attributes``; a member without ``attributes``
        counts as one without a photo.
    LDAP_PHOTO_ATTRIBUTE: attribute that holds the photo.
    RBAC_SYNC_CONTAINER_BIN, RBAC_SYNC_CID: how to reach the Jellyfin container.
    JELLYFIN_API: Jellyfin's URL inside its container.
    JELLYFIN_API_CLIENT: value of the ``X-Emby-Authorization`` header.
    JELLYFIN_ADMIN_USERNAME, JELLYFIN_ADMIN_PASSWORD: the local administrator.

Output:
    One ``CHANGED <username> photo`` line per pushed photo, else ``UNCHANGED``.
"""

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

STATE_FILE = Path("state.json")
USERS_ROLE = "@users"
TIMEOUT_SECONDS = "60"


def directory_photos(environ):
    """Return ``{username: photo octets}`` of every account that has a photo.

    Args:
        environ: the process environment.
    """
    photo = environ["LDAP_PHOTO_ATTRIBUTE"]
    members = json.loads(
        Path(environ["RBAC_SYNC_MEMBERS_FILE"]).read_text(encoding="utf-8")
    )[f"{USERS_ROLE}:{photo}"]
    encoded = {
        member["username"]: member["attributes"][photo]
        for member in members
        if "attributes" in member
    }
    return {
        username: base64.b64decode(value)
        for username, value in encoded.items()
        if value
    }


def api(environ, run, path, method, body, headers):
    """Return the body of one Jellyfin API answer, requested inside the container.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        path: path below the API URL.
        method: the HTTP method.
        body: the request body, or None.
        headers: the request headers.
    """
    config = [
        f"url = {json.dumps(environ['JELLYFIN_API'] + path)}",
        f"request = {json.dumps(method)}",
        *(
            f"header = {json.dumps(f'{name}: {value}', ensure_ascii=False)}"
            for name, value in headers.items()
        ),
    ]
    if body is not None:
        config.append(f"data-binary = {json.dumps(body, ensure_ascii=False)}")
    argv = [
        environ["RBAC_SYNC_CONTAINER_BIN"],
        "exec",
        "-i",
        environ["RBAC_SYNC_CID"],
        "curl",
        "-sS",
        "-f",
        "--max-time",
        TIMEOUT_SECONDS,
        "-K",
        "-",
    ]
    result = run(
        argv,
        input="\n".join(config) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"curl exited {result.returncode} on {method} {path}: {result.stderr.strip()}"
        )
    return result.stdout


def main(environ, run=subprocess.run, state_file=STATE_FILE):
    """Push every changed directory photo and print the result.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        state_file: where the pushed digests are remembered.
    """
    photos = directory_photos(environ)
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
            run,
            "/Users/AuthenticateByName",
            "POST",
            json.dumps(
                {
                    "Username": environ["JELLYFIN_ADMIN_USERNAME"],
                    "Pw": environ["JELLYFIN_ADMIN_PASSWORD"],
                }
            ),
            client,
        )
    )
    authorization = {"Authorization": f'MediaBrowser Token="{session["AccessToken"]}"'}
    accounts = {
        user["Name"]: user["Id"]
        for user in json.loads(api(environ, run, "/Users", "GET", None, authorization))
    }
    lines = []
    for username, image in sorted(photos.items()):
        digest = hashlib.sha256(image).hexdigest()
        if username not in accounts or pushed.get(username) == digest:
            continue
        api(
            environ,
            run,
            f"/UserImage?userId={accounts[username]}",
            "POST",
            base64.b64encode(image).decode(),
            {**authorization, "Content-Type": "image/jpeg"},
        )
        pushed[username] = digest
        lines.append(f"CHANGED {username} photo")
    state_file.write_text(json.dumps(pushed, sort_keys=True), encoding="utf-8")
    print("\n".join(lines) or "UNCHANGED")


if __name__ == "__main__":
    main(os.environ)
