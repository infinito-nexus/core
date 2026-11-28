"""Converge LiteLLM's proxy_admin role on the administrator role group.

Environment:
    LITELLM_PORT: port the gateway listens on inside its container.
    LITELLM_MASTER_KEY: the gateway's master key.
    RBAC_ADMINISTRATORS: JSON list of the administrator role's members.
    LITELLM_RBAC_KEEP: JSON list of user ids that keep their role.

Output:
    One ``CHANGED <user id> <role>`` line per changed user, else ``UNCHANGED``.
"""

import json
import os
import urllib.request

PROXY_ADMIN = "proxy_admin"
INTERNAL_USER = "internal_user"
PAGE_SIZE = 100


def call(environ, path, payload, opener):
    """Return the decoded JSON answer of one authenticated gateway request.

    Args:
        environ: the process environment.
        path: path below the gateway URL, query included.
        payload: JSON body of a POST, or None for a GET.
        opener: ``urllib.request.urlopen`` or a stand-in.
    """
    request = urllib.request.Request(
        f"http://127.0.0.1:{environ['LITELLM_PORT']}{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + environ["LITELLM_MASTER_KEY"],
            "Content-Type": "application/json",
        },
        method="GET" if payload is None else "POST",
    )
    with opener(request, timeout=30) as response:
        return json.loads(response.read().decode())


def users(environ, opener):
    """Return every user of the gateway, across all pages.

    Args:
        environ: the process environment.
        opener: ``urllib.request.urlopen`` or a stand-in.
    """
    found = []
    page = 1
    while True:
        answer = call(
            environ, f"/user/list?page={page}&page_size={PAGE_SIZE}", None, opener
        )
        found.extend(answer["users"])
        if page >= answer["total_pages"]:
            return found
        page += 1


def plan(accounts, members, keep):
    """Return ``(user id, role)`` pairs that bring the roles in line with the group.

    Args:
        accounts: the gateway's users.
        members: ``[{"username", "email"}]`` of the administrator role.
        keep: user ids that keep their role.
    """
    ids = {member["username"] for member in members}
    emails = {member["email"].lower() for member in members if member["email"]}
    changes = []
    for account in accounts:
        user_id = account["user_id"]
        if user_id in keep:
            continue
        member = user_id in ids or (account.get("user_email") or "").lower() in emails
        role = account["user_role"]
        if member and role != PROXY_ADMIN:
            changes.append((user_id, PROXY_ADMIN))
        elif not member and role == PROXY_ADMIN:
            changes.append((user_id, INTERNAL_USER))
    return changes


def main(environ, opener=urllib.request.urlopen):
    """Apply the plan and print the result.

    Args:
        environ: the process environment.
        opener: ``urllib.request.urlopen`` or a stand-in.
    """
    changes = plan(
        users(environ, opener),
        json.loads(environ["RBAC_ADMINISTRATORS"]),
        set(json.loads(environ["LITELLM_RBAC_KEEP"])),
    )
    for user_id, role in changes:
        call(environ, "/user/update", {"user_id": user_id, "user_role": role}, opener)
    print(
        "\n".join(f"CHANGED {user_id} {role}" for user_id, role in changes)
        or "UNCHANGED"
    )


if __name__ == "__main__":
    main(os.environ)
