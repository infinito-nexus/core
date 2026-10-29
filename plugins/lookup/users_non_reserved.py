from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.reserved_users import non_reserved_users
from utils.cache.base import _resolve_override_mapping


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('users_non_reserved') }}
        {{ lookup('users_non_reserved', pinned_only=true) }}

    Returns the users an identity directory provisions -- those carrying
    ``identity`` in ``accounts`` -- as the same dict shape ``lookup('users')``
    yields. Every consumer that provisions or references directory users must
    read this, so no two of them can disagree about who exists.

    Args:
        pinned_only: keep only users whose password the inventory ``users``
            override pins. Any other user's password is a fresh random value on
            every evaluation, so a consumer that writes it into a file would
            rewrite that file on every deploy.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if terms:
            raise AnsibleError("lookup('users_non_reserved') expects no terms.")

        pinned_only = bool(kwargs.pop("pinned_only", False))
        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}
        users = lookup_loader.get(
            "users",
            loader=getattr(self, "_loader", None),
            templar=templar,
        ).run([], variables=variables, **kwargs)[0]

        selected = non_reserved_users(users)
        if pinned_only:
            overrides = _resolve_override_mapping(variables, "users", templar=templar)
            selected = {
                key: user
                for key, user in selected.items()
                if isinstance(overrides.get(key), Mapping)
                and overrides[key].get("password")
            }
        return [selected]
