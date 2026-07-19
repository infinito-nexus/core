"""Lookup plugin: enumerate roles whose merged config has
``services.sso.flavor == 'oauth2'`` AND ``services.sso.enabled`` truthy.

Returned as a list of role names (``application_id`` strings), in the
deterministic alphabetical order of the merged-applications keys.

Usage:
    {{ lookup('sso_proxy_consumers') }}

No positional terms are accepted. Predicate logic delegates to
``utils.roles.applications.services.sso.get_sso_config`` so callers
share one source of truth with ``lookup('sso', ..., 'is_proxy_gated')``
and ``plugins/filter/compose_volumes.py``.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.services.sso import get_sso_config


class LookupModule(LookupBase):
    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if terms:
            raise AnsibleError(
                "lookup('sso_proxy_consumers') takes no positional terms."
            )

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(self._templar, "available_variables", {}) or {}

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=variables)[0]

        consumers: list[str] = [
            app_id
            for app_id in sorted(applications.keys())
            if get_sso_config(applications, app_id)["is_proxy_gated"]
        ]
        return [consumers]
