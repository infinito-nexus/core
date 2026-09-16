from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.api import provider_enabled, resolve_api


class LookupModule(LookupBase):
    """
    lookup('api_enabled', '<provider>')  e.g. lookup('api_enabled', 'github')

    True when every credential the provider declares in group_vars/all/18_api.yml
    carries a value in the effective ``API`` mapping. Integrations that depend on
    a proprietary provider gate on this instead of spelling the emptiness test
    out per call site, so an added credential key extends the gate everywhere and
    the result is a real boolean rather than a string a filter has to coerce.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('api_enabled') takes exactly one term: '<provider>' "
                "(e.g. 'github')."
            )

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}

        provider = str(terms[0]).strip()
        if not provider:
            raise AnsibleError("lookup('api_enabled'): empty provider name.")

        try:
            api = resolve_api(variables, templar=templar)
            return [provider_enabled(api, provider)]
        except (KeyError, TypeError) as error:
            raise AnsibleError(f"lookup('api_enabled'): {error}") from error
