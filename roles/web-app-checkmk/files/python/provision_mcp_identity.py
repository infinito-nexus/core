# nocheck: mirrored-unit-test - reads the administrator credential from the container
# environment at import and every helper is one authenticated REST call against the
# live Checkmk site; a mocked transport would assert the mock, not the identity
"""Give the MCP adapter its own read-only Checkmk identity.

Checkmk accepts a caller-chosen automation secret, so the identity is the
deployment's own credential rather than one captured from a response. The
adapter then presents ``Bearer <user> <secret>``.

The built-in ``guest`` role can read monitoring state but not the Setup domain,
so ``/domain-types/host_config/collections/all`` would answer with an empty
list rather than the host inventory. A clone of ``guest`` with the two Setup
read permissions is what makes that tool return anything.

A 401 stays a verdict and must fail on the first attempt: Checkmk locks a user
after ten failed logins, so retrying a wrong administrator password locks the
account the deployment needs, and no later run can unlock it from here. The
manager-ops pass writes the declared password onto the running site before this
script runs, which is what keeps a starting site from answering 401 at all.

Environment:
    CHECKMK_API:            REST API base, ending in /check_mk/api/1.0.
    CHECKMK_ADMIN_USER:     administrator to act as.
    CHECKMK_ADMIN_PASSWORD: that administrator's password.
    CHECKMK_SITE:           site id, for the activation call.
    MCP_USER:               username to converge.
    MCP_SECRET:             automation secret to pin on it.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ["CHECKMK_API"].rstrip("/")
ADMIN_USER = os.environ["CHECKMK_ADMIN_USER"]
ADMIN_PASSWORD = os.environ["CHECKMK_ADMIN_PASSWORD"]
SITE = os.environ["CHECKMK_SITE"]
MCP_USER = os.environ["MCP_USER"]
MCP_SECRET = os.environ["MCP_SECRET"]

ROLE_ID = "mcpreadonly"
BASE_ROLE = "guest"
TIMEOUT = 30

changed = {"any": False}


def call(method, path, payload=None, headers=None):
    """Return ``(status, parsed body)`` of one REST API call.

    Args:
        method: HTTP method.
        path: path below the API base.
        payload: JSON body, or None.
        headers: extra headers, or None.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{API}{path}", data=data, method=method)  # noqa: S310 fixed internal http origin
    request.add_header("Authorization", f"Bearer {ADMIN_USER} {ADMIN_PASSWORD}")
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


def ids(collection):
    return {str(entry.get("id")) for entry in (collection or {}).get("value") or []}


def ensure_role():
    status, body = call("GET", "/domain-types/user_role/collections/all")
    if status != 200:
        fail(f"listing user roles answered {status}: {body}", status)

    if ROLE_ID not in ids(body):
        status, body = call(
            "POST",
            "/domain-types/user_role/collections/all",
            {
                "role_id": BASE_ROLE,
                "new_role_id": ROLE_ID,
                "new_alias": "MCP read-only",
            },
        )
        if status not in (200, 201):
            fail(f"cloning {BASE_ROLE} answered {status}: {body}", status)
        changed["any"] = True

    status, body = call(
        "PUT",
        f"/objects/user_role/{ROLE_ID}",
        {"new_permissions": {"wato.use": "yes", "wato.see_all_folders": "yes"}},
        {"If-Match": "*"},
    )
    if status != 200:
        fail(f"granting Setup read to {ROLE_ID} answered {status}: {body}", status)


def ensure_user():
    status, body = call("GET", "/domain-types/user_config/collections/all")
    if status != 200:
        fail(f"listing users answered {status}: {body}", status)

    secret = {
        "auth_type": "automation",
        "secret": MCP_SECRET,
        "store_automation_secret": False,
    }
    if MCP_USER in ids(body):
        status, body = call(
            "PUT",
            f"/objects/user_config/{MCP_USER}",
            {"auth_option": secret, "roles": [ROLE_ID]},
            {"If-Match": "*"},
        )
        if status != 200:
            fail(f"rotating {MCP_USER} answered {status}: {body}", status)
        return

    status, body = call(
        "POST",
        "/domain-types/user_config/collections/all",
        {
            "username": MCP_USER,
            "fullname": "MCP read-only adapter",
            "roles": [ROLE_ID],
            "auth_option": secret,
            "disable_login": False,
        },
    )
    if status not in (200, 201):
        fail(f"creating {MCP_USER} answered {status}: {body}", status)
    changed["any"] = True


def activate():
    status, body = call(
        "POST",
        "/domain-types/activation_run/actions/activate-changes/invoke",
        {"redirect": False, "sites": [SITE], "force_foreign_changes": False},
        {"If-Match": "*"},
    )
    if status not in (200, 201, 302, 422):
        fail(f"activating changes answered {status}: {body}", status)


def main():
    ensure_role()
    ensure_user()
    activate()
    print("CHANGED" if changed["any"] else "UNCHANGED")


if __name__ == "__main__":
    main()
