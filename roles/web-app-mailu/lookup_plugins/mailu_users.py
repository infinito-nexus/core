"""Lookup ``mailu_users``: the subset of the user catalogue Mailu provisions.

``lookup('users')`` yields every user any role declares -- 291 of them in a full
CI round -- while Mailu acts on seven. Looping the whole catalogue and letting
each task's ``when:`` discard the rest still pays a task execution per user per
task, which measured 259.5s of a single job.

A user is Mailu's when it carries a mailbox account, or when it is a bot, whose
API token Mailu issues. Both halves are needed: the token task is gated on the
role, not on the account, so filtering by mailbox alone would silently stop
issuing tokens to a bot that has no mailbox of its own.

The per-task ``when:`` conditions stay in place. This set is a superset of what
each of them selects, so it decides how often they are evaluated, never their
outcome.

Returns the same dict shape ``lookup('users')`` yields, so call sites keep
``| dict2items`` and ``user_item.value.*`` unchanged.

Usage, through the constant in ``vars/main.yml``:

    MAILU_USERS: "{{ lookup('mailu_users') }}"
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
            f"mailu_users: user '{user.get('username', '?')}' declares "
            f"{key}={value!r}; a list is required."
        )
    return [str(entry) for entry in value]


def provisioned_by_mailu(user: dict[str, Any]) -> bool:
    """Return whether Mailu acts on this user at all."""
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
            raise AnsibleError("mailu_users lookup takes no positional terms")

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
                if isinstance(user, dict) and provisioned_by_mailu(user)
            }
        ]
