"""Lookup `stage_groups`: the ordered role-group names
(``tasks/groups/<g>-roles.yml``) that belong to a deploy stage, in intra-stage
call order. The stage plays loop over it so group membership follows
``roles/categories.yml`` instead of a hardcoded list:

    loop: "{{ lookup('stage_groups', 'server') }}"
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.roles.stage import stage_groups


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "stage_groups lookup requires exactly one term: the stage"
            )
        return [stage_groups(str(terms[0]).strip())]
