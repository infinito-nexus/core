"""Monitor the runner pool of the infra runner as one Checkmk host.

A missing local check file stays PENDING rather than REJECTED: the infra
runner's timer writes it only once its first run ends.

Environment:
    CHECKMK_API:            REST API base, ending in /check_mk/api/1.0.
    CHECKMK_ADMIN_USER:     administrator to act as.
    CHECKMK_ADMIN_PASSWORD: that administrator's password.
    CHECKMK_SITE:           site id, for the activation call.
    POOL_HOST:              host name the pool services land on.
    POOL_FILE:              the mounted local check file, as the site sees it.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import time
import urllib.error
import urllib.request
from functools import partial
from pathlib import Path

TIMEOUT = 30
TRANSIENT_STATUS = frozenset({0, 409, 429, 502, 503, 504})
LOOPBACK = "127.0.0.1"
RULESET = "datasource_programs"
MARKER = "infinito-nexus runner pool"
DISCOVERY_MODE = "fix_all"
DISCOVERY_POLLS = 60
DISCOVERY_POLL_SECONDS = 2


class CheckmkError(RuntimeError):
    """
    Args:
        message: what went wrong.
        status: the HTTP status that caused it, 0 without an answer.
    """

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def call(api, user, password, method, path, payload=None, headers=None):
    """Return ``(status, parsed body)`` of one REST API call.

    Args:
        api: REST API base.
        user: administrator to act as.
        password: that administrator's password.
        method: HTTP method.
        path: path below the API base.
        payload: JSON body, or None.
        headers: extra headers, or None.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{api}{path}", data=data, method=method)  # noqa: S310 fixed internal http origin
    request.add_header("Authorization", f"Bearer {user} {password}")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 fixed internal http origin
            body = response.read()
            return response.status, json.loads(body or b"null")
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            return error.code, json.loads(body or b"null")
        except ValueError:
            return error.code, {"detail": body.decode(errors="replace")}
    except OSError as error:
        return 0, {"detail": f"unreachable: {error}"}


def program(path):
    """
    Args:
        path: the mounted local check file.

    Returns:
        The datasource program that prints it.
    """
    return f"cat {path}"


def ensure_host(api, host):
    """
    Args:
        api: the REST call of :func:`call`, bound to the site.
        host: host name the pool services land on.

    Returns:
        True when the host had to be created.
    """
    status, body = api("GET", f"/objects/host_config/{host}")
    if status == 200:
        return False
    if status != 404:
        raise CheckmkError(f"reading host {host} answered {status}: {body}", status)
    status, body = api(
        "POST",
        "/domain-types/host_config/collections/all",
        {"folder": "/", "host_name": host, "attributes": {"ipaddress": LOOPBACK}},
    )
    if status not in (200, 201):
        raise CheckmkError(f"creating host {host} answered {status}: {body}", status)
    return True


def _value(rule):
    try:
        return ast.literal_eval((rule.get("extensions") or {}).get("value_raw") or "")
    except (SyntaxError, ValueError):
        return None


def _ours(rule):
    extensions = rule.get("extensions") or {}
    return (extensions.get("properties") or {}).get("description") == MARKER


def ensure_rule(api, host, command):
    """
    Args:
        api: the REST call of :func:`call`, bound to the site.
        host: host name the pool services land on.
        command: the datasource program of the host.

    Returns:
        True when the rule had to be created or rewritten.
    """
    status, body = api(
        "GET", f"/domain-types/rule/collections/all?ruleset_name={RULESET}"
    )
    if status != 200:
        raise CheckmkError(f"listing {RULESET} answered {status}: {body}", status)
    spec = {
        "properties": {"description": MARKER, "disabled": False},
        "value_raw": repr(command),
        "conditions": {"host_name": {"match_on": [host], "operator": "one_of"}},
    }
    ours = [rule for rule in (body or {}).get("value") or [] if _ours(rule)]
    if ours and _value(ours[0]) == command:
        return False
    if ours:
        status, body = api(
            "PUT", f"/objects/rule/{ours[0]['id']}", spec, {"If-Match": "*"}
        )
    else:
        status, body = api(
            "POST",
            "/domain-types/rule/collections/all",
            {"ruleset": RULESET, "folder": "/", **spec},
        )
    if status not in (200, 201):
        raise CheckmkError(
            f"writing the {RULESET} rule answered {status}: {body}", status
        )
    return True


def activate(api, site):
    """
    Args:
        api: the REST call of :func:`call`, bound to the site.
        site: site id.
    """
    status, body = api(
        "POST",
        "/domain-types/activation_run/actions/activate-changes/invoke",
        {"redirect": False, "sites": [site], "force_foreign_changes": False},
        {"If-Match": "*"},
    )
    if status not in (200, 201, 302, 422):
        raise CheckmkError(f"activating changes answered {status}: {body}", status)


def discover(api, host, sleep):
    """
    Args:
        api: the REST call of :func:`call`, bound to the site.
        host: host name the pool services land on.
        sleep: waits the given seconds between two polls.
    """
    status, body = api(
        "POST",
        "/domain-types/service_discovery_run/actions/start/invoke",
        {"host_name": host, "mode": DISCOVERY_MODE},
    )
    if status not in (200, 201, 202, 302):
        raise CheckmkError(f"discovering {host} answered {status}: {body}", status)
    for _ in range(DISCOVERY_POLLS):
        status, body = api("GET", f"/objects/service_discovery_run/{host}")
        if status != 200:
            raise CheckmkError(
                f"polling the discovery of {host} answered {status}: {body}", status
            )
        if not ((body or {}).get("extensions") or {}).get("active"):
            return
        sleep(DISCOVERY_POLL_SECONDS)
    raise CheckmkError(f"the discovery of {host} still runs", 0)


def register(api, host, command, site, sleep):
    """
    Args:
        api: the REST call of :func:`call`, bound to the site.
        host: host name the pool services land on.
        command: the datasource program of the host.
        site: site id.
        sleep: waits the given seconds between two discovery polls.

    Returns:
        True when the host or its rule changed.
    """
    changed = ensure_host(api, host)
    changed = ensure_rule(api, host, command) or changed
    activate(api, site)
    discover(api, host, sleep)
    activate(api, site)
    return changed


def register_from(env) -> bool:
    """
    Args:
        env: POOL_FILE, CHECKMK_API, CHECKMK_ADMIN_USER,
            CHECKMK_ADMIN_PASSWORD, POOL_HOST and CHECKMK_SITE.

    Returns:
        True when the host or its rule changed.

    Raises:
        CheckmkError: the pool file is not written yet (status 0), or a REST
            call failed.
    """
    path = env["POOL_FILE"]
    if not Path(path).is_file():
        raise CheckmkError(f"{path} is not written yet", 0)
    api = partial(
        call,
        env["CHECKMK_API"].rstrip("/"),
        env["CHECKMK_ADMIN_USER"],
        env["CHECKMK_ADMIN_PASSWORD"],
    )
    return register(
        api, env["POOL_HOST"], program(path), env["CHECKMK_SITE"], time.sleep
    )


def main():
    try:
        changed = register_from(os.environ)
    except CheckmkError as error:
        marker = "PENDING" if error.status in TRANSIENT_STATUS else "REJECTED"
        sys.stderr.write(f"{marker} {error}\n")
        return 1
    print("CHANGED" if changed else "UNCHANGED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
