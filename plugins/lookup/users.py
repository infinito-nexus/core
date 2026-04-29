from __future__ import annotations

from typing import Any, Dict, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache import _reset_cache_for_tests as _reset_runtime_lookup_cache
from utils.cache.users import get_merged_users


def _reset_cache_for_tests() -> None:
    _reset_runtime_lookup_cache()


class LookupModule(LookupBase):
    def run(
        self,
        terms: Optional[list[Any]],
        variables: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) > 2:
            raise AnsibleError(
                "users: expected 0, 1, or 2 terms: "
                "lookup('users'[, canonical_user_key[, default]])"
            )

        users = get_merged_users(
            variables=variables
            or getattr(self._templar, "available_variables", {})
            or {},
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )

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
