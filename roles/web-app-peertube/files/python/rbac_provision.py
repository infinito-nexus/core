"""Create the missing OIDC accounts of the role group members through the PeerTube API.

Args (module global, prepended on stdin by tasks/rbac/provision.yml):
    PAYLOAD_B64: base64 of a JSON object with
        url: PeerTube's URL inside its network namespace;
        hostname: Host header PeerTube answers to;
        root_username, root_password: the local root account;
        role_ids: ``{role: PeerTube role id}`` of administrator and moderator;
        members: ``{role: [{username, email, name}]}`` of administrator and moderator.

Output:
    ``{"created": [email, ...], "failed": [{username, status, body, warning}, ...]}``
    on stdout: the e-mails of the members whose account now exists, and every
    member whose account could not be created (``warning: false``) or whose
    username or e-mail a local account of somebody else holds (``warning:
    true``), named. A member whose username or e-mail an OIDC account already
    holds is skipped: the plugin owns that identity, and PeerTube keeps the
    e-mail it first saw. The exit code is 1 only when an account could not be
    created. The RBAC hook hands an account to the OIDC plugin only while nobody
    has used it. Proxy variables of the environment are ignored.
"""

import base64
import json
import secrets
import string
import sys
import urllib.error
import urllib.parse
import urllib.request

PASSWORD_ALPHABET = string.ascii_letters + string.digits
PAGE_SIZE = 100


def ranked_members(members, role_ids):
    """Return every member with an e-mail and the highest PeerTube role it holds.

    Args:
        members: ``{role: [{username, email, name}]}``.
        role_ids: ``{role: PeerTube role id}``.
    """
    administrators = [m for m in members["administrator"] if m["email"]]
    taken = {m["username"] for m in administrators}
    moderators = [
        m for m in members["moderator"] if m["email"] and m["username"] not in taken
    ]
    return [
        {
            "username": m["username"],
            "email": m["email"],
            "role": role_ids["administrator"],
        }
        for m in administrators
    ] + [
        {"username": m["username"], "email": m["email"], "role": role_ids["moderator"]}
        for m in moderators
    ]


def api(payload, opener, path, data=None, form=False, token=""):
    """Return the decoded JSON answer of one PeerTube API request.

    Args:
        payload: the decoded ``PAYLOAD_B64``.
        opener: ``open`` of a ``urllib.request`` opener, or a stand-in.
        path: path below the PeerTube URL, query included.
        data: request body, or None for a GET.
        form: whether the body is form-encoded instead of JSON.
        token: bearer token, or an empty string.
    """
    headers = {"Host": payload["hostname"]}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(  # noqa: S310 - payload url is PeerTube inside its own network namespace
        payload["url"] + path, data=body, headers=headers
    )
    with opener(request, timeout=60) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def root_token(payload, opener):
    """Return an access token of the local root account.

    Args:
        payload: the decoded ``PAYLOAD_B64``.
        opener: ``open`` of a ``urllib.request`` opener, or a stand-in.
    """
    client = api(payload, opener, "/api/v1/oauth-clients/local")
    return api(
        payload,
        opener,
        "/api/v1/users/token",
        {
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "grant_type": "password",
            "username": payload["root_username"],
            "password": payload["root_password"],
        },
        form=True,
    )["access_token"]


def accounts(payload, opener, token):
    """Return ``{username: {"email": lower-cased e-mail, "plugin": pluginAuth}}`` of every account.

    Args:
        payload: the decoded ``PAYLOAD_B64``.
        opener: ``open`` of a ``urllib.request`` opener, or a stand-in.
        token: the root access token.
    """
    found, start = {}, 0
    while True:
        page = api(
            payload,
            opener,
            f"/api/v1/users?start={start}&count={PAGE_SIZE}&sort=createdAt",
            token=token,
        )
        for account in page["data"]:
            found[account["username"]] = {
                "email": account["email"].lower(),
                "plugin": account["pluginAuth"],
            }
        start += len(page["data"])
        if not page["data"] or start >= page["total"]:
            return found


def conflict(member, existing):
    """Return why a local account of somebody else holds the member's username or e-mail, or None.

    Only local accounts count: an OIDC account under the member's username or
    e-mail is the member's own, and its e-mail may lag behind the directory.

    Args:
        member: one entry of ``ranked_members``.
        existing: ``accounts`` before the run.
    """
    email = member["email"].lower()
    local = {
        name: account["email"]
        for name, account in existing.items()
        if account["plugin"] is None
    }
    held = local.get(member["username"])
    if held is not None and held != email:
        return (
            f"username {member['username']} is held by an account with another e-mail"
        )
    holders = sorted(
        name
        for name, address in local.items()
        if address == email and name != member["username"]
    )
    if holders:
        return f"e-mail of {member['username']} is held by account {holders[0]}"
    return None


def claimed(member, existing):
    """Return whether an account already carries the member's username or e-mail.

    Args:
        member: one entry of ``ranked_members``.
        existing: ``accounts`` before the run.
    """
    email = member["email"].lower()
    return member["username"] in existing or any(
        account["email"] == email for account in existing.values()
    )


def account_exists(payload, opener, token, member):
    """Return whether one account carries both the member's username and e-mail.

    Args:
        payload: the decoded ``PAYLOAD_B64``.
        opener: ``open`` of a ``urllib.request`` opener, or a stand-in.
        token: the root access token.
        member: one entry of ``ranked_members``.
    """
    query = urllib.parse.urlencode({"search": member["email"], "count": PAGE_SIZE})
    found = api(payload, opener, f"/api/v1/users?{query}", token=token)["data"]
    return any(
        account["email"].lower() == member["email"].lower()
        and account["username"] == member["username"]
        for account in found
    )


def _failure(member, error):
    if isinstance(error, urllib.error.HTTPError):
        body = error.read().decode("utf-8", "replace")
        return {
            "username": member["username"],
            "status": error.code,
            "body": body[:500],
            "warning": False,
        }
    return {
        "username": member["username"],
        "status": None,
        "body": str(error)[:500],
        "warning": False,
    }


def create(payload, opener, token, member):
    """Create one member's account; return None, or the named failure.

    PeerTube also answers 409 for a taken channel name or the actor of a deleted
    account, so a 409 counts only when the account exists afterwards.

    Args:
        payload: the decoded ``PAYLOAD_B64``.
        opener: ``open`` of a ``urllib.request`` opener, or a stand-in.
        token: the root access token.
        member: one entry of ``ranked_members``.
    """
    try:
        api(
            payload,
            opener,
            "/api/v1/users",
            {
                "username": member["username"],
                "email": member["email"],
                "password": "".join(
                    secrets.choice(PASSWORD_ALPHABET) for _ in range(48)
                ),
                "role": int(member["role"]),
            },
            token=token,
        )
    except urllib.error.HTTPError as error:
        failure = _failure(member, error)
        if error.code == 409:
            try:
                if account_exists(payload, opener, token, member):
                    return None
            except (OSError, ValueError) as lookup_error:
                failure["body"] += f" (re-query failed: {lookup_error})"
        return failure
    except (OSError, ValueError) as error:
        return _failure(member, error)
    return None


def main(payload, opener):
    """Create the accounts of the members without one, print the outcome, return the exit code.

    Args:
        payload: the decoded ``PAYLOAD_B64``.
        opener: ``open`` of a ``urllib.request`` opener, or a stand-in.
    """
    ranked = ranked_members(payload["members"], payload["role_ids"])
    created, failed = [], []
    if ranked:
        token = root_token(payload, opener)
        existing = accounts(payload, opener, token)
        for member in ranked:
            reason = conflict(member, existing)
            if reason is not None:
                failed.append(
                    {
                        "username": member["username"],
                        "status": None,
                        "body": reason,
                        "warning": True,
                    }
                )
                continue
            if claimed(member, existing):
                continue
            failure = create(payload, opener, token, member)
            if failure is None:
                created.append(member["email"])
            else:
                failed.append(failure)
    json.dump({"created": created, "failed": failed}, sys.stdout)
    return 1 if any(not failure["warning"] for failure in failed) else 0


if __name__ == "__main__":
    sys.exit(
        main(
            json.loads(base64.b64decode(globals()["PAYLOAD_B64"]).decode()),
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open,
        )
    )
