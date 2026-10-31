from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 120


def request(
    method: str,
    url: str,
    token: str,
    fields: dict[str, str | list[str]] | None = None,
    files: dict[str, tuple[str, str, bytes]] | None = None,
) -> tuple[int, object]:
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if files:
        boundary = secrets.token_hex(16)
        data = multipart(boundary, fields or {}, files)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif fields:
        data = urllib.parse.urlencode(fields, doseq=True).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    outgoing = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 https URL of a local Fediverse source
    try:
        with urllib.request.urlopen(outgoing, timeout=TIMEOUT) as response:  # noqa: S310 https URL of a local Fediverse source
            status, raw = response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read().decode()
    except (urllib.error.URLError, OSError) as error:
        return 0, str(error)
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, raw


def multipart(
    boundary: str,
    fields: dict[str, str | list[str]],
    files: dict[str, tuple[str, str, bytes]],
) -> bytes:
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{single}\r\n'.encode()
        for name, value in fields.items()
        for single in (value if isinstance(value, list) else [value])
    ]
    for name, (filename, mime, content) in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n".encode()
            + content
            + b"\r\n"
        )
    return b"".join(parts) + f"--{boundary}--\r\n".encode()


def mastodon_post(
    base: str,
    token: str,
    text: str,
    image: tuple[str, str, bytes] | None,
    spoiler: str,
) -> dict:
    fields: dict[str, str | list[str]] = {"status": text, "visibility": "public"}
    if spoiler:
        fields["spoiler_text"] = spoiler
    if image:
        status, media = request(
            "POST",
            f"{base}/api/v2/media",
            token,
            {"description": "A plain colour square"},
            {"file": image},
        )
        if status not in (200, 202) or not isinstance(media, dict):
            return {"error": f"media upload HTTP {status} {media}"}
        fields["media_ids[]"] = [str(media["id"])]
        time.sleep(2)
    status, body = request("POST", f"{base}/api/v1/statuses", token, fields)
    if status != 200 or not isinstance(body, dict):
        return {"error": f"status HTTP {status} {body}"}
    return body


def mastodon_statuses(base: str, token: str, account: str) -> list[dict]:
    status, found = request(
        "GET", f"{base}/api/v1/accounts/lookup?acct={account}", token
    )
    if status != 200 or not isinstance(found, dict):
        return []
    status, body = request(
        "GET", f"{base}/api/v1/accounts/{found['id']}/statuses?limit=40", token
    )
    return body if status == 200 and isinstance(body, list) else []


def pixelfed_post(
    base: str, token: str, text: str, image: tuple[str, str, bytes]
) -> dict:
    status, media = request(
        "POST",
        f"{base}/api/v1/media",
        token,
        {"description": "A plain colour square"},
        {"file": image},
    )
    if status != 200 or not isinstance(media, dict):
        return {"error": f"media upload HTTP {status} {media}"}
    status, body = request(
        "POST",
        f"{base}/api/v1/statuses",
        token,
        {"status": text, "visibility": "public", "media_ids[]": [str(media["id"])]},
    )
    if status != 200 or not isinstance(body, dict):
        return {"error": f"status HTTP {status} {body}"}
    return body


def peertube_upload(
    base: str,
    token: str,
    channel: str,
    name: str,
    tag: str,
    video: tuple[str, str, bytes],
) -> dict:
    status, found = request("GET", f"{base}/api/v1/video-channels/{channel}", token)
    if status != 200 or not isinstance(found, dict):
        return {"error": f"channel HTTP {status} {found}"}
    status, body = request(
        "POST",
        f"{base}/api/v1/videos/upload",
        token,
        {
            "channelId": str(found["id"]),
            "name": name,
            "description": f"{name} #{tag}",
            "privacy": "1",
            "waitTranscoding": "false",
            "tags[]": [tag],
        },
        {"videofile": video},
    )
    if status != 200 or not isinstance(body, dict):
        return {"error": f"upload HTTP {status} {body}"}
    return body["video"]
