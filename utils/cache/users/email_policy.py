"""Primary and secondary addresses of the cached user records per email policy."""

from __future__ import annotations

from typing import Any


def apply_email_policy(users: dict[str, Any], mailbox: bool) -> dict[str, Any]:
    """Give every user record its primary and secondary address.

    Args:
        users: user records, unrendered.
        mailbox: True under the ``mailbox`` policy.

    Returns:
        ``users`` where, under ``mailbox``, ``email`` is
        ``<username>@<DOMAIN_PRIMARY>`` and ``secondary_email`` the address
        the record declared; under ``external``, ``secondary_email`` is empty.
    """
    for key, user in users.items():
        if not isinstance(user, dict) or "email" not in user:
            continue
        if mailbox:
            user["secondary_email"] = user["email"]
            user["email"] = f"{user.get('username', key)}@{{{{ DOMAIN_PRIMARY }}}}"
        else:
            user["secondary_email"] = ""
    return users


def drop_mail_domain_secondaries(users: dict[str, Any]) -> dict[str, Any]:
    """Clear every rendered secondary address inside the mailbox domain.

    Args:
        users: rendered user records.

    Returns:
        ``users`` where a ``secondary_email`` that shares the domain of
        ``email`` is empty, since the user profile refuses such an address.
    """
    for user in users.values():
        if not isinstance(user, dict) or not user.get("secondary_email"):
            continue
        domain = str(user["email"]).rpartition("@")[2].lower()
        if str(user["secondary_email"]).lower().endswith("@" + domain):
            user["secondary_email"] = ""
    return users
