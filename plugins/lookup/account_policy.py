from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache import ROLES_DIR
from utils.roles import account_policy

DERIVED = {
    "username_max_length": account_policy.username_max_length,
    "account_max_length": account_policy.account_max_length,
    "username_patterns": account_policy.username_patterns,
}


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('account_policy', 'username_max_length') }}
        {{ lookup('account_policy', 'account_max_length') }}
        {{ lookup('account_policy', 'username_patterns') }}

    Returns the IAM limit derived from every role's meta/account.yml: the
    smallest username limit of all roles, the smallest of the agent-reachable
    ones, or the sorted distinct username patterns.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if not terms or len(terms) != 1 or terms[0] not in DERIVED:
            raise AnsibleError(
                f"lookup('account_policy') expects one of {sorted(DERIVED)}."
            )
        return [DERIVED[terms[0]](account_policy.load_policies(ROLES_DIR))]
