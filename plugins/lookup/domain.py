# lookup_plugins/domain.py
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.domains import get_merged_domains


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('domain', application_id) }}

    Resolves the canonical primary domain for `application_id` via
    utils.cache.domains.get_merged_domains (cached). Per-app overrides
    belong in `applications.<app>.server.domains` and flow through the
    regular applications-merge pipeline.
    """

    def run(self, terms, variables: Optional[Dict[str, Any]] = None, **kwargs):
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('domain', application_id) expects exactly 1 term"
            )

        application_id = terms[0]
        if not isinstance(application_id, str) or not application_id.strip():
            raise AnsibleError(
                f"lookup('domain'): application_id must be a non-empty string, got {application_id!r}"
            )

        variables = variables or getattr(self._templar, "available_variables", {}) or {}

        domains = get_merged_domains(
            variables=variables,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )

        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(plugin_dir, "..", ".."))
        if project_root not in sys.path:
            sys.path.append(project_root)

        try:
            from utils.domains.primary_domain import get_domain
        except Exception as e:
            raise AnsibleError(
                f"lookup('domain'): could not import utils.domains.primary_domain.get_domain: {e}"
            )

        try:
            domain = get_domain(domains, application_id.strip())
        except Exception as e:
            raise AnsibleError(
                f"lookup('domain'): failed to resolve domain for '{application_id}': {e}"
            )

        return [domain]
