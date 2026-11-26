from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

# nocheck: lookup-cache-import (this lookup IS the applications SPOT provider)
from utils.cache.applications import get_lazy_applications, get_merged_applications
from utils.cache.base import _fingerprint_scope
from utils.cache.carrier import merged_applications_cache_key
from utils.cache.reset import _reset_cache_for_tests as _reset_runtime_lookup_cache


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
            1) application_id
            2) application_id, default value

        Keyword arguments:
            roles_dir: roles tree to build from (defaults to the repository's)
            carrier: with no terms, return ``{"key": [...], "applications": {...}}``
                for the constructor to park in `_INFINITO_APPLICATIONS_RENDERED`
        """
        terms = terms or []
        if len(terms) > 2:
            raise AnsibleError(
                "applications: expected 0, 1, or 2 terms: "
                "lookup('applications'[, application_id[, default]])"
            )
        carrier = bool(kwargs.get("carrier", False))
        if carrier and terms:
            raise AnsibleError("applications: carrier=True takes no terms")

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        with _fingerprint_scope():
            return self._resolve(terms, variables, kwargs.get("roles_dir"), carrier)

    def _resolve(
        self,
        terms: list[Any],
        variables: dict[str, Any],
        roles_dir: Any,
        carrier: bool,
    ) -> list[Any]:
        """
        Args:
            terms: the validated lookup terms.
            variables: the variables scope of the lookup.
            roles_dir: roles tree to build from, ``None`` for the project's own.
            carrier: return the carrier form instead of the mapping.

        Returns:
            The one-element lookup result.
        """
        templar = getattr(self, "_templar", None)
        if carrier or not terms:
            applications = get_merged_applications(
                variables=variables, roles_dir=roles_dir, templar=templar
            )
            if not carrier:
                return [applications]
            key = merged_applications_cache_key(variables, roles_dir=roles_dir)
            return [{"key": [key[0], list(key[1])], "applications": applications}]

        applications = get_lazy_applications(
            variables=variables, roles_dir=roles_dir, templar=templar
        )
        application_id = str(terms[0]).strip()
        default_provided = len(terms) == 2
        default_value = terms[1] if default_provided else None

        if application_id in applications:
            return [applications[application_id]]

        if default_provided:
            return [default_value]

        raise AnsibleError(
            f"applications: application '{application_id}' not found. "
            f"Known application ids: {sorted(applications)}"
        )
