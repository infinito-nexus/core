"""Ansible lookup wrapper around
``utils.roles.meta_lookup.iter_roles_with_default_placement``.

    lookup('roles_with_default_placement', 'manager')
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.roles.meta_lookup import iter_roles_with_default_placement


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        terms = terms or []
        if len(terms) != 1:
            raise AnsibleError(
                "roles_with_default_placement: expected exactly 1 term, "
                "the placement value (e.g. 'manager')"
            )
        return [iter_roles_with_default_placement(str(terms[0]))]
