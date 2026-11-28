from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

TIMEOUT = 30


class Unredirected(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def rest_api(base, user, secret, cafile):
    """Args:
    base: the REST API base, ending in ``/check_mk/api/1.0``.
    user: the automation user.
    secret: its automation secret.
    cafile: the CA bundle the site's certificate chains to.

    Returns:
        The call function ``Checkmk`` takes.
    """
    context = ssl.create_default_context(cafile=cafile)
    # Exception: urllib re-sends the Authorization header to any redirect target, so Unredirected turns a 3xx into its status instead of following it.
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), Unredirected
    )

    # A site or proxy may echo the request, Authorization header included, into its answer.
    def redacted(raw):
        return raw.replace(secret.encode(), b"<secret>") if secret else raw

    def call(method, path, payload=None, headers=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(  # noqa: S310 the site URL comes from the platform deploy
            f"{base.rstrip('/')}{path}", data=data, method=method
        )
        request.add_header("Authorization", f"Bearer {user} {secret}")
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with opener.open(request, timeout=TIMEOUT) as response:
                body = redacted(response.read())
                return response.status, json.loads(body or b"null")
        except urllib.error.HTTPError as error:
            body = redacted(error.read())
            try:
                return error.code, json.loads(body or b"null")
            except ValueError:
                return error.code, {"detail": body.decode(errors="replace")}

    return call
