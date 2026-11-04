from __future__ import annotations

from typing import Any


def _request(
    email: str, method: str, path: str, body: dict[str, Any]
) -> dict[str, Any]:
    return {"email": email, "method": method, "path": path, "body": body}


def mailu_rbac_mailboxes(usernames: list[str], domain: str) -> list[str]:
    """Return the mailboxes of the usernames in the mail domain.

    Args:
        usernames: login names, in any case, possibly repeated.
        domain: the mail domain.

    Returns:
        One ``<lowercased username>@<domain>`` per distinct username, in first-seen order.
    """
    return [
        f"{name}@{domain}" for name in dict.fromkeys(name.lower() for name in usernames)
    ]


def mailu_rbac_plan(
    users: list[dict[str, Any]],
    managers: list[str],
    admin_mailboxes: list[str],
    manager_mailboxes: list[str],
    domain: str,
) -> list[dict[str, Any]]:
    """List the Mailu API requests that converge the roles with the RBAC members.

    Args:
        users: ``GET /user`` response, each entry with ``email`` and ``global_admin``.
        managers: ``managers`` of the ``GET /domain/<domain>/manager`` response.
        admin_mailboxes: lowercase mailboxes that hold ``global_admin``.
        manager_mailboxes: lowercase mailboxes that manage ``domain``.
        domain: the mail domain whose managers are converged.

    Returns:
        ``[{"email", "method", "path", "body"}]``: a ``PATCH /user/`` per
        ``global_admin`` flag to flip, a ``POST`` per wanted manager that has
        a mailbox and is missing, a ``DELETE`` per manager no longer wanted.
    """
    accounts = [user["email"].lower() for user in users]
    current = [manager.lower() for manager in managers]
    wanted = [mailbox for mailbox in manager_mailboxes if mailbox in accounts]
    manager_path = f"/domain/{domain}/manager"
    return (
        [
            _request(user["email"], "PATCH", "/user/", {"global_admin": True})
            for user in users
            if not user["global_admin"] and user["email"] in admin_mailboxes
        ]
        + [
            _request(user["email"], "PATCH", "/user/", {"global_admin": False})
            for user in users
            if user["global_admin"] and user["email"] not in admin_mailboxes
        ]
        + [
            _request(mailbox, "POST", manager_path, {})
            for mailbox in wanted
            if mailbox not in current
        ]
        + [
            _request(mailbox, "DELETE", f"{manager_path}/", {})
            for mailbox in current
            if mailbox not in wanted
        ]
    )
