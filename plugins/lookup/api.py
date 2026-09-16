from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.api import resolve_api


class LookupModule(LookupBase):
    """
    lookup('api', '<provider>.<key>')  e.g. lookup('api', 'github.client_id')

    Single point of truth for proprietary / external API credentials. Resolves a
    dotted path against the effective ``API`` mapping: the declaration in
    group_vars/all/18_api.yml with the calling scope's override merged over it.
    Routing every access through this plugin keeps one place to change how
    proprietary API credentials are sourced (vault, env, secret manager, a
    different provider abstraction) without touching the call sites.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('api') takes exactly one term: '<provider>.<key>' "
                "(e.g. 'github.client_id')."
            )

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}

        path = str(terms[0]).strip()
        if not path:
            raise AnsibleError("lookup('api'): empty key path.")

        try:
            api = resolve_api(variables, templar=templar)
        except TypeError as error:
            raise AnsibleError(f"lookup('api'): {error}") from error

        node: Any = api
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise AnsibleError(
                    f"lookup('api'): unknown key '{path}' (failed at '{part}'). "
                    f"Declare it under 'API' in group_vars/all/18_api.yml."
                )
            node = node[part]
        return [node]
