from __future__ import annotations

from typing import Any


def stalwart_admin_plan(
    accounts: list[dict[str, Any]],
    domain_id: str,
    admin_names: list[str],
    admin_role_id: str,
) -> dict[str, list[str]]:
    """Pick the accounts that gain and those that lose System Administrator.

    Args:
        accounts: ``x:Account/get`` list of every principal.
        domain_id: id of the mail domain whose user accounts are reconciled.
        admin_names: account names that hold System Administrator.
        admin_role_id: id of the built-in System Administrator role.

    Returns:
        ``{"grant_ids": [...], "revoke_ids": [...]}``: the ids of the domain's
        user accounts named in ``admin_names``, and of the other domain user
        accounts whose ``roles.roleIds`` still carry ``admin_role_id``.
    """
    users = [
        account
        for account in accounts
        if account.get("@type") == "User" and account.get("domainId") == domain_id
    ]
    return {
        "grant_ids": [
            account["id"] for account in users if account["name"] in admin_names
        ],
        "revoke_ids": [
            account["id"]
            for account in users
            if account["name"] not in admin_names
            and admin_role_id in ((account.get("roles") or {}).get("roleIds") or {})
        ],
    }
