# lookup_plugins/domains.py
from __future__ import annotations

from typing import Any, Dict, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache import _reset_cache_for_tests as _reset_runtime_lookup_cache
from utils.cache.domains import get_merged_domains


def _reset_cache_for_tests() -> None:
    _reset_runtime_lookup_cache()


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('domains') }}                          -> full canonical-domains map
        {{ lookup('domains', application_id) }}          -> subtree for one role
        {{ lookup('domains', application_id, default) }} -> subtree with fallback

    Behavior:
        Builds (and caches) the canonical-domains map via
        utils.cache.domains.get_merged_domains. Per-app overrides belong
        in `applications.<app>.server.domains` (canonical/aliases) and flow
        through the regular applications-merge pipeline. No upstream set_fact
        required.
    """

    def run(
        self,
        terms: Optional[list[Any]],
        variables: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) > 2:
            raise AnsibleError(
                "lookup('domains'[, application_id[, default]]) expects 0, 1 or 2 terms."
            )

        variables = variables or getattr(self._templar, "available_variables", {}) or {}

        domains = get_merged_domains(
            variables=variables,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )

        if len(terms) == 0:
            return [domains]

        application_id = str(terms[0]).strip()
        default_provided = len(terms) == 2
        default_value = terms[1] if default_provided else None

        if application_id in domains:
            return [domains[application_id]]

        if default_provided:
            return [default_value]

        raise AnsibleError(
            f"lookup('domains'): application '{application_id}' not found. "
            f"Known application ids: {sorted(domains)}"
        )
