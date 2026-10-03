"""Lookup ``stalwart_users``: the subset of the user catalogue Stalwart provisions.

``lookup('users')`` yields every user any role declares -- 295 of them in a full
CI round -- while Stalwart acts on seven. The rest are the ``accounts: []`` name
reservations ``utils.cache.users`` mints for every role-name suffix; creating a
JMAP account for one contradicts the empty declaration and hands an
authenticable SMTP/IMAP principal to a name that exists only to block squatting.

A user is Stalwart's when it carries a mailbox account, or when it is a bot,
whose submission credential ``sys-token-store`` persists. Both halves are
needed: the token task is gated on the role, not on the account, so filtering by
mailbox alone would silently stop issuing a credential to a bot that has no
mailbox of its own.

Mirrors ``roles/web-app-mailu/lookup_plugins/mailu_users.py`` so the two mail
providers select the same set from the same contract.

Returns the same dict shape ``lookup('users')`` yields, so call sites keep
``| dict2items`` and ``user_item.value.*`` unchanged.

Usage, through the constant in ``vars/main.yml``:

    STALWART_USERS: "{{ lookup('stalwart_users') }}"
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

MAILBOX_ACCOUNT = "mailbox"
BOT_ROLE = "bot"


def _string_list(user: dict[str, Any], key: str) -> list[str]:
    """Read one list-valued user attribute, defaulting to empty.

    Args:
        user: one entry of the merged user catalogue.
        key: attribute name, ``accounts`` or ``roles``.

    Raises:
        AnsibleError: the attribute is present but is not a list.
    """
    value = user.get(key, [])
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise AnsibleError(
            f"stalwart_users: user '{user.get('username', '?')}' declares "
            f"{key}={value!r}; a list is required."
        )
    return [str(entry) for entry in value]


def provisioned_by_stalwart(user: dict[str, Any]) -> bool:
    """Return whether Stalwart acts on this user at all."""
    return MAILBOX_ACCOUNT in _string_list(
        user, "accounts"
    ) or BOT_ROLE in _string_list(user, "roles")


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if terms:
            raise AnsibleError("stalwart_users lookup takes no positional terms")

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        users = lookup_loader.get(
            "users",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        ).run([], variables=variables, **kwargs)[0]

        return [
            {
                key: user
                for key, user in users.items()
                if isinstance(user, dict) and provisioned_by_stalwart(user)
            }
        ]
