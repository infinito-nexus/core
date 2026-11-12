from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache import _reset_cache_for_tests as _reset_runtime_lookup_cache
from utils.cache.carrier import merged_users_cache_key

# nocheck: lookup-cache-import (this lookup IS the users SPOT provider)
from utils.cache.users import get_merged_users


def _reset_cache_for_tests() -> None:
    _reset_runtime_lookup_cache()


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """
        Terms:
            0) full merged mapping
            1) canonical_user_key
            2) canonical_user_key, default value

        Keyword arguments:
            roles_dir: roles tree to build from (defaults to the repository's)
            carrier: with no terms, return ``{"key": [...], "users": {...}}``
                for the constructor to park in `_INFINITO_USERS_RENDERED`
        """
        terms = terms or []
        if len(terms) > 2:
            raise AnsibleError(
                "users: expected 0, 1, or 2 terms: "
                "lookup('users'[, canonical_user_key[, default]])"
            )
        carrier = bool(kwargs.get("carrier", False))
        if carrier and terms:
            raise AnsibleError("users: carrier=True takes no terms")

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        roles_dir = kwargs.get("roles_dir")
        users = get_merged_users(
            variables=variables,
            roles_dir=roles_dir,
            templar=getattr(self, "_templar", None),
        )

        if carrier:
            key = merged_users_cache_key(variables, roles_dir=roles_dir)
            return [{"key": [key[0], list(key[1])], "users": users}]

        if len(terms) == 0:
            return [users]

        user_key = str(terms[0]).strip()
        default_provided = len(terms) == 2
        default_value = terms[1] if default_provided else None

        if user_key in users:
            return [users[user_key]]

        if default_provided:
            return [default_value]

        raise AnsibleError(
            f"users: user '{user_key}' not found. Known user keys: {sorted(users)}"
        )
