from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.reserved_users import non_reserved_users


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('users_non_reserved') }}

    Returns the users an identity directory provisions -- those carrying
    ``identity`` in ``accounts`` -- as the same dict shape ``lookup('users')``
    yields. Every consumer that provisions or references directory users must
    read this, so no two of them can disagree about who exists.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if terms:
            raise AnsibleError("lookup('users_non_reserved') expects no terms.")

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        users = lookup_loader.get(
            "users",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        ).run([], variables=variables, **kwargs)[0]

        return [non_reserved_users(users)]
