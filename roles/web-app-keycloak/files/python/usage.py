from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 30
PAGE = 100
REQUEST_KEYS = frozenset(
    {
        "enabled",
        "host",
        "url",
        "realm",
        "client_id",
        "secret",
        "admin",
        "cafile",
        "result_dir",
    }
)
HOST = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.:_-]{0,252}$")


class UsageError(Exception):
    pass


def opener(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
    """
    Args:
        *handlers: the handlers that open a URL.

    Returns:
        An opener that follows no redirect and raises on every answer outside 2xx.
    """
    director = urllib.request.OpenerDirector()
    for handler in (
        *handlers,
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        director.add_handler(handler)
    return director


def tls_opener(cafile: str) -> urllib.request.OpenerDirector:
    """
    Args:
        cafile: the deployment CA trusted instead of the system store, or empty.

    Returns:
        An https-only opener through the proxy of the environment, verifying
        certificate and host name, TLS 1.2 or newer.
    """
    context = ssl.create_default_context(cafile=cafile or None)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return opener(
        urllib.request.ProxyHandler(), urllib.request.HTTPSHandler(context=context)
    )


def active(user: dict, admin: str) -> bool:
    """
    Args:
        user: one user representation of the realm.
        admin: the username of the master realm's technical administrator.

    Returns:
        Whether the user is an enabled person: no service account and not
        the technical administrator.
    """
    return (
        user.get("enabled") is True
        and not user.get("serviceAccountClientId")
        and str(user.get("username", "")).lower() != admin.lower()
    )


def fetch(director: urllib.request.OpenerDirector, request: urllib.request.Request):
    """
    Args:
        director: the opener every request goes through.
        request: the request.

    Returns:
        The decoded JSON body.
    """
    try:
        with director.open(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        error.close()
        path = urllib.parse.urlsplit(request.full_url).path
        raise UsageError(f"{request.get_method()} {path}: HTTP {error.code}") from None


def count(request: dict, director: urllib.request.OpenerDirector) -> int:
    """
    Args:
        request: the validated request.
        director: the opener every request goes through.

    Returns:
        The number of active people of the realm, read page by page.
    """
    realm = urllib.parse.quote(request["realm"], safe="")
    origin = request["url"].rstrip("/")
    form = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": request["client_id"],
            "client_secret": request["secret"],
        }
    ).encode()
    token = fetch(
        director,
        urllib.request.Request(  # noqa: S310 https origin checked in main()
            f"{origin}/realms/{realm}/protocol/openid-connect/token",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        ),
    )["access_token"]
    total = 0
    first = 0
    while True:
        query = urllib.parse.urlencode(
            {"first": first, "max": PAGE, "briefRepresentation": "false"}
        )
        page = fetch(
            director,
            urllib.request.Request(  # noqa: S310 https origin checked in main()
                f"{origin}/admin/realms/{realm}/users?{query}",
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            ),
        )
        total += sum(1 for user in page if active(user, request["admin"]))
        if len(page) < PAGE:
            return total
        first += len(page)


def validated(raw: str) -> dict:
    """
    Args:
        raw: the request text from standard input.

    Returns:
        The request with ``enabled`` as a boolean.
    """
    request = json.loads(raw)
    if not isinstance(request, dict) or set(request) != REQUEST_KEYS:
        raise UsageError("the request does not hold exactly the usage fields")
    if not HOST.match(str(request["host"])):
        raise UsageError("the host is malformed")
    request["enabled"] = str(request["enabled"]).lower() == "true"
    if request["enabled"] and not str(request["url"]).startswith("https://"):
        raise UsageError("the Keycloak origin is no https origin")
    return request


def main(argv: list[str], stdin=sys.stdin) -> int:
    """
    Args:
        argv: the command line; takes no argument.
        stdin: one JSON object: ``enabled`` (the host's usage client switch),
            ``host`` (the inventory host), ``url`` (the https origin of
            Keycloak), ``realm`` (the application realm), ``client_id`` and
            ``secret`` (the usage client, the secret empty while it is off),
            ``admin`` (the master realm's technical administrator),
            ``cafile`` (the deployment CA, or empty) and ``result_dir``.

    Returns:
        The exit code; 0 after ``<result_dir>/<host>.json`` received
        ``host``, ``realm`` and ``active_users``, null without a call while
        the client is off, and one ``usage`` line went to standard output;
        1 with the reason, never the secret, on standard error.
    """
    if len(argv) != 1:
        print("usage.py: takes no argument", file=sys.stderr)
        return 1
    try:
        request = validated(stdin.read())
        active_users = (
            count(request, tls_opener(request["cafile"]))
            if request["enabled"]
            else None
        )
    except (UsageError, OSError, ValueError, KeyError, TypeError) as error:
        reason = error if isinstance(error, UsageError) else type(error).__name__
        print(f"usage.py: {reason}", file=sys.stderr)
        return 1
    result = {
        "host": request["host"],
        "realm": request["realm"],
        "active_users": active_users,
    }
    Path(request["result_dir"], f"{request['host']}.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    print(
        f"usage host={request['host']} realm={request['realm']} active_users={active_users}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
